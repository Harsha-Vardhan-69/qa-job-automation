import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd

from .constants import KEYWORDS, KEYWORD_REGEX_PATTERNS, RELAXED_KEYWORD_REGEX_PATTERNS
from .env_config import compact, usd_to_inr


def parse_datetime(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)

    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 10_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc)
        except Exception:
            return None

    text = compact(value)
    if not text:
        return None

    lowered = text.lower()
    now = datetime.now(timezone.utc)
    if lowered in {"just posted", "today", "few seconds ago", "a few seconds ago"}:
        return now
    if lowered == "yesterday":
        return now - timedelta(days=1)

    relative_patterns = [
        (r"(\d+)\s*minute", "minutes"),
        (r"(\d+)\s*hour", "hours"),
        (r"(\d+)\s*day", "days"),
    ]
    for pattern, unit in relative_patterns:
        match = re.search(pattern, lowered)
        if match:
            value_num = int(match.group(1))
            if unit == "minutes":
                return now - timedelta(minutes=value_num)
            if unit == "hours":
                return now - timedelta(hours=value_num)
            return now - timedelta(days=value_num)

    parsed = pd.to_datetime(text, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def format_iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def normalize_location(location: str) -> str:
    text = compact(location).lower()
    if not text:
        return "Not listed"

    if any(token in text for token in ("bengaluru", "bangalore", "blr")):
        return "Bangalore"
    if any(token in text for token in ("hyderabad", "hyd")):
        return "Hyderabad"

    india_remote_tokens = (
        "remote india",
        "india remote",
        "work from home india",
        "wfh india",
        "india (remote)",
    )
    if any(token in text for token in india_remote_tokens):
        return "Remote India"

    global_remote_tokens = (
        "global remote",
        "remote global",
        "worldwide remote",
        "anywhere",
        "apac remote",
        "remote apac",
    )
    if any(token in text for token in global_remote_tokens):
        return "Global remote"

    if "remote" in text:
        return "Global remote"
    return compact(location)


def classify_job_type(location: str, title: str) -> str:
    text = f"{location} {title}".lower()
    if "remote" in text or "work from home" in text or "wfh" in text:
        return "Remote"
    if "hybrid" in text:
        return "Hybrid"
    return "Onsite"


def location_matches_constraint(location: str, job_type: str) -> bool:
    normalized = normalize_location(location).lower()
    if normalized in {"hyderabad", "bangalore", "remote india", "global remote"}:
        return True
    if "remote" in normalized:
        return True
    return compact(job_type).lower() == "remote"


def location_quality_score(location: str, job_type: str) -> int:
    normalized = normalize_location(location).lower()
    if normalized in {"hyderabad", "bangalore"}:
        return 12
    if normalized == "remote india":
        return 10
    if normalized == "global remote":
        return 8
    if compact(job_type).lower() == "remote":
        return 8
    return 2


def _keyword_haystack(title: str, skills: str, extra_text: str = "") -> str:
    return f"{compact(title)} {compact(skills)} {compact(extra_text)}".lower()


def keyword_score(title: str, skills: str, extra_text: str = "", relaxed: bool = False) -> int:
    haystack = _keyword_haystack(title, skills, extra_text)
    base_score = 0

    for keyword in KEYWORDS:
        if keyword.lower() in haystack:
            base_score += 4

    patterns = RELAXED_KEYWORD_REGEX_PATTERNS if relaxed else KEYWORD_REGEX_PATTERNS
    for pattern in patterns:
        if pattern.search(haystack):
            base_score += 3

    return min(base_score, 30)


def keyword_matches(title: str, skills: str, extra_text: str = "", relaxed: bool = False) -> bool:
    threshold = 3 if relaxed else 4
    return keyword_score(title=title, skills=skills, extra_text=extra_text, relaxed=relaxed) >= threshold


def match_quality_label(score: float) -> str:
    if score >= 80:
        return "High"
    if score >= 60:
        return "Medium"
    return "Low"


def salary_lpa_from_text(text: str) -> float | None:
    lowered = compact(text).lower()
    if not lowered or lowered == "not listed":
        return None

    lpa_values = [float(v) for v in re.findall(r"(\d+(?:\.\d+)?)\s*(?:lpa|lakh|lakhs|lac|lacs)", lowered)]
    if lpa_values:
        return sum(lpa_values) / len(lpa_values)

    range_match = re.search(
        r"(\d[\d,]*(?:\.\d+)?)\s*(?:-|to)\s*(\d[\d,]*(?:\.\d+)?)",
        lowered,
    )
    if range_match:
        amount = (float(range_match.group(1).replace(",", "")) + float(range_match.group(2).replace(",", ""))) / 2
    else:
        numbers = re.findall(r"\d[\d,]*(?:\.\d+)?", lowered)
        if not numbers:
            return None
        amount = float(numbers[0].replace(",", ""))

    if " lakh" in lowered or " lac" in lowered:
        amount *= 100_000
    elif re.search(r"\bk\b|thousand", lowered):
        amount *= 1_000
    elif re.search(r"\bm\b|million", lowered):
        amount *= 1_000_000

    if "month" in lowered:
        amount *= 12
    elif "week" in lowered:
        amount *= 52
    elif "day" in lowered:
        amount *= 260
    elif "hour" in lowered:
        amount *= 2080

    if "$" in lowered or "usd" in lowered:
        amount *= usd_to_inr()

    return amount / 100_000


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _annualize_amount(amount: float, period: str) -> float:
    if period == "month":
        return amount * 12
    if period == "week":
        return amount * 52
    if period == "day":
        return amount * 260
    if period == "hour":
        return amount * 2080
    return amount


def _inr_amount(amount: float, currency: str) -> float:
    return amount * usd_to_inr() if currency == "USD" else amount


def salary_lpa(job: dict[str, Any]) -> float | None:
    min_salary = job.get("_salary_min")
    max_salary = job.get("_salary_max")
    currency = compact(job.get("_salary_currency")).upper()
    period = compact(job.get("_salary_period")).lower()

    numeric_candidates: list[float] = []
    for value in (min_salary, max_salary):
        numeric_value = _to_float(value)
        if numeric_value is not None:
            numeric_candidates.append(numeric_value)

    if numeric_candidates:
        amount = sum(numeric_candidates) / len(numeric_candidates)
        amount = _annualize_amount(amount, period)
        amount = _inr_amount(amount, currency)
        return amount / 100_000

    return salary_lpa_from_text(compact(job.get("Salary")))


def display_salary(job: dict[str, Any]) -> str:
    min_salary = job.get("_salary_min")
    max_salary = job.get("_salary_max")
    currency = compact(job.get("_salary_currency")).upper() or "INR"
    period = compact(job.get("_salary_period")).lower() or "year"

    min_salary_num = _to_float(min_salary)
    max_salary_num = _to_float(max_salary)

    if min_salary_num is not None or max_salary_num is not None:
        if min_salary_num is not None:
            min_inr = _inr_amount(_annualize_amount(min_salary_num, period), currency)
            min_lpa = min_inr / 100_000
        else:
            min_lpa = None

        if max_salary_num is not None:
            max_inr = _inr_amount(_annualize_amount(max_salary_num, period), currency)
            max_lpa = max_inr / 100_000
        else:
            max_lpa = None

        if min_lpa is not None and max_lpa is not None:
            if abs(min_lpa - max_lpa) < 0.01:
                return f"{min_lpa:.2f} LPA"
            return f"{min_lpa:.2f} - {max_lpa:.2f} LPA"
        if min_lpa is not None:
            return f"{min_lpa:.2f} LPA"
        if max_lpa is not None:
            return f"{max_lpa:.2f} LPA"

    salary_text = compact(job.get("Salary"))
    if salary_text and salary_text.lower() != "not listed":
        lpa = salary_lpa_from_text(salary_text)
        if lpa is not None:
            return f"{lpa:.2f} LPA"

    return "Not listed"
