import argparse
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup

JOB_COLUMNS = [
    "Job Title",
    "Company",
    "Location",
    "Salary",
    "Source",
    "Direct Apply Link",
    "Posted Date",
    "Experience Required",
    "Required Skills",
    "Job Type (Remote / Hybrid / Onsite)",
    "Job ID",
    "Application Deadline",
]

KEYWORDS = [
    "QA Tester",
    "Quality Assurance Engineer",
    "Software Test Engineer",
    "SDET",
    "QA Analyst",
    "Test Automation Engineer",
    "Selenium Automation Engineer",
]

LOCATION_QUERIES = [
    "Hyderabad",
    "Bangalore",
    "Remote India",
    "Global remote",
]

TARGET_SOURCES = {
    "LinkedIn",
    "Naukri",
    "Indeed",
    "Glassdoor",
    "Company career pages",
    "Wellfound",
    "Instahyre",
    "Cutshort",
    "Hirist",
    "YC Work at a Startup",
    "RemoteOK",
}

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
REQUEST_TIMEOUT_SECONDS = 25
USD_TO_INR = float(os.getenv("USD_TO_INR", "83.0"))


def compact(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


def classify_job_type(location: str, title: str) -> str:
    text = f"{location} {title}".lower()
    if "remote" in text or "work from home" in text:
        return "Remote"
    if "hybrid" in text:
        return "Hybrid"
    return "Onsite"


def location_matches_constraint(location: str, job_type: str) -> bool:
    text = compact(location).lower()
    if "hyderabad" in text or "bangalore" in text or "bengaluru" in text:
        return True
    if "remote" in text:
        return True
    if job_type == "Remote":
        return True
    return False


def keyword_matches(title: str, skills: str) -> bool:
    haystack = f"{title} {skills}".lower()
    keyword_aliases = [kw.lower() for kw in KEYWORDS] + [
        "qa engineer",
        "quality assurance",
        "manual testing",
        "automation testing",
        "software testing",
    ]
    return any(alias in haystack for alias in keyword_aliases)


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
        amount *= USD_TO_INR

    return amount / 100_000


def salary_lpa(job: dict[str, Any]) -> float | None:
    min_salary = job.get("_salary_min")
    max_salary = job.get("_salary_max")
    currency = compact(job.get("_salary_currency")).upper()
    period = compact(job.get("_salary_period")).lower()

    numeric_candidates: list[float] = []
    for value in (min_salary, max_salary):
        try:
            if value is not None:
                numeric_candidates.append(float(value))
        except (TypeError, ValueError):
            pass

    if numeric_candidates:
        amount = sum(numeric_candidates) / len(numeric_candidates)
        if period == "month":
            amount *= 12
        elif period == "week":
            amount *= 52
        elif period == "day":
            amount *= 260
        elif period == "hour":
            amount *= 2080

        if currency == "USD":
            amount *= USD_TO_INR
        return amount / 100_000

    return salary_lpa_from_text(compact(job.get("Salary")))


def display_salary(job: dict[str, Any]) -> str:
    salary_text = compact(job.get("Salary"))
    if salary_text and salary_text.lower() != "not listed":
        return salary_text

    min_salary = job.get("_salary_min")
    max_salary = job.get("_salary_max")
    currency = compact(job.get("_salary_currency")) or "INR"
    period = compact(job.get("_salary_period")) or "year"

    if min_salary is None and max_salary is None:
        return "Not listed"

    if min_salary is not None and max_salary is not None:
        return f"{min_salary} - {max_salary} {currency}/{period}"
    if min_salary is not None:
        return f"{min_salary} {currency}/{period}"
    return f"{max_salary} {currency}/{period}"


def jsearch_source_name(raw_publisher: str, apply_link: str) -> str | None:
    publisher = compact(raw_publisher).lower()
    link = compact(apply_link).lower()

    if "linkedin" in publisher or "linkedin" in link:
        return "LinkedIn"
    if "naukri" in publisher or "naukri" in link:
        return "Naukri"
    if "indeed" in publisher or "indeed" in link:
        return "Indeed"
    if "glassdoor" in publisher or "glassdoor" in link:
        return "Glassdoor"
    if "wellfound" in publisher or "angel.co" in link or "wellfound" in link:
        return "Wellfound"
    if "instahyre" in publisher or "instahyre" in link:
        return "Instahyre"
    if "cutshort" in publisher or "cutshort" in link:
        return "Cutshort"
    if "hirist" in publisher or "hirist" in link:
        return "Hirist"

    company_page_tokens = [
        "greenhouse",
        "lever",
        "workday",
        "smartrecruiters",
        "ashby",
        "icims",
        "careers",
        "career",
        "company",
    ]
    if any(token in publisher for token in company_page_tokens) or any(token in link for token in company_page_tokens):
        return "Company career pages"

    return None


def fetch_indeed_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    base_url = "https://in.indeed.com/jobs"

    for keyword in KEYWORDS:
        for location in LOCATION_QUERIES:
            try:
                response = requests.get(
                    base_url,
                    params={"q": keyword, "l": location, "fromage": "1"},
                    headers={"User-Agent": USER_AGENT},
                    timeout=REQUEST_TIMEOUT_SECONDS,
                )
                response.raise_for_status()
            except Exception as exc:
                print(f"[WARN] Indeed fetch failed for '{keyword}' in '{location}': {exc}")
                continue

            soup = BeautifulSoup(response.text, "html.parser")
            for card in soup.select(".job_seen_beacon"):
                title_el = card.select_one("h2 a span")
                company_el = card.select_one(".companyName")
                if not title_el or not company_el:
                    continue

                title = compact(title_el.get_text())
                company = compact(company_el.get_text())
                location_el = card.select_one(".companyLocation")
                salary_el = card.select_one(".salary-snippet-container")
                date_el = card.select_one(".date")
                snippet_el = card.select_one(".job-snippet")
                link_el = card.select_one("h2 a")
                href = link_el.get("href", "") if link_el else ""
                link = f"https://in.indeed.com{href}" if href else "Not listed"

                jobs.append(
                    {
                        "Job Title": title,
                        "Company": company,
                        "Location": compact(location_el.get_text()) if location_el else "Not listed",
                        "Salary": compact(salary_el.get_text()) if salary_el else "Not listed",
                        "Source": "Indeed",
                        "Direct Apply Link": link,
                        "Posted Date": compact(date_el.get_text()) if date_el else "",
                        "Experience Required": "Not listed",
                        "Required Skills": compact(snippet_el.get_text()) if snippet_el else "Not listed",
                        "Job Type (Remote / Hybrid / Onsite)": "Not listed",
                        "Job ID": link.split("jk=")[-1] if "jk=" in link else "",
                        "Application Deadline": "Not listed",
                    }
                )

    return jobs


def fetch_remoteok_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    try:
        response = requests.get(
            "https://remoteok.com/api",
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        print(f"[WARN] RemoteOK fetch failed: {exc}")
        return jobs

    if not isinstance(payload, list):
        return jobs

    for item in payload:
        if not isinstance(item, dict) or "position" not in item:
            continue

        jobs.append(
            {
                "Job Title": compact(item.get("position")),
                "Company": compact(item.get("company")),
                "Location": compact(item.get("location")) or "Global remote",
                "Salary": compact(item.get("salary")) or "Not listed",
                "Source": "RemoteOK",
                "Direct Apply Link": compact(item.get("url")) or "Not listed",
                "Posted Date": item.get("date") or item.get("epoch") or "",
                "Experience Required": "Not listed",
                "Required Skills": ", ".join(item.get("tags") or []) or "Not listed",
                "Job Type (Remote / Hybrid / Onsite)": "Remote",
                "Job ID": str(item.get("id") or ""),
                "Application Deadline": "Not listed",
                "_salary_min": item.get("salary_min"),
                "_salary_max": item.get("salary_max"),
                "_salary_currency": "USD",
                "_salary_period": "year",
            }
        )

    return jobs


def fetch_yc_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    endpoints = [
        "https://www.workatastartup.com/api/jobs",
        "https://www.workatastartup.com/api/job-board",
    ]

    for endpoint in endpoints:
        try:
            response = requests.get(
                endpoint,
                headers={"User-Agent": USER_AGENT},
                timeout=REQUEST_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            continue

        candidates: list[dict[str, Any]] = []
        if isinstance(payload, list):
            candidates = [item for item in payload if isinstance(item, dict)]
        elif isinstance(payload, dict):
            if isinstance(payload.get("jobs"), list):
                candidates = [item for item in payload["jobs"] if isinstance(item, dict)]
            elif isinstance(payload.get("data"), list):
                candidates = [item for item in payload["data"] if isinstance(item, dict)]

        for item in candidates:
            title = compact(item.get("title") or item.get("role") or item.get("jobTitle"))
            company = compact(item.get("company") or item.get("company_name") or item.get("startup_name"))
            if not title or not company:
                continue

            raw_location = item.get("location")
            if raw_location:
                location = compact(raw_location)
            elif item.get("remote") is True:
                location = "Global remote"
            else:
                location = "Not listed"
            link = compact(item.get("url") or item.get("apply_url") or item.get("job_url"))
            tags = item.get("tags")
            if isinstance(tags, list):
                skills = ", ".join(str(tag) for tag in tags)
            else:
                skills = compact(item.get("skills") or item.get("description")) or "Not listed"

            jobs.append(
                {
                    "Job Title": title,
                    "Company": company,
                    "Location": location,
                    "Salary": compact(item.get("salary")) or "Not listed",
                    "Source": "YC Work at a Startup",
                    "Direct Apply Link": link or "Not listed",
                    "Posted Date": item.get("updated_at") or item.get("created_at") or "",
                    "Experience Required": compact(item.get("experience")) or "Not listed",
                    "Required Skills": skills,
                    "Job Type (Remote / Hybrid / Onsite)": classify_job_type(location, title),
                    "Job ID": str(item.get("id") or ""),
                    "Application Deadline": compact(item.get("application_deadline")) or "Not listed",
                }
            )

        if jobs:
            break

    if not jobs:
        print("[WARN] YC Work at a Startup API returned no parseable jobs.")

    return jobs


def fetch_jsearch_jobs() -> list[dict[str, Any]]:
    api_key = os.getenv("RAPIDAPI_KEY", "").strip()
    if not api_key:
        print("[WARN] RAPIDAPI_KEY not set. Skipping JSearch-backed sources.")
        return []

    jobs: list[dict[str, Any]] = []
    endpoint = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": api_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }

    for keyword in KEYWORDS:
        for location in LOCATION_QUERIES:
            query = f"{keyword} in {location}"
            params = {
                "query": query,
                "page": "1",
                "num_pages": "1",
                "date_posted": "today",
            }
            try:
                response = requests.get(endpoint, headers=headers, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
                response.raise_for_status()
                data = response.json().get("data", [])
            except Exception as exc:
                print(f"[WARN] JSearch fetch failed for '{query}': {exc}")
                continue

            for item in data:
                apply_link = compact(item.get("job_apply_link") or item.get("job_google_link"))
                source = jsearch_source_name(item.get("job_publisher"), apply_link)
                if source is None or source not in TARGET_SOURCES:
                    continue

                city = compact(item.get("job_city"))
                state = compact(item.get("job_state"))
                country = compact(item.get("job_country"))
                location_parts = [part for part in [city, state, country] if part]
                location_text = ", ".join(location_parts) if location_parts else "Not listed"
                if item.get("job_is_remote"):
                    location_text = "Global remote" if location_text == "Not listed" else f"{location_text} (Remote)"

                skills = item.get("job_required_skills")
                if isinstance(skills, list):
                    skill_text = ", ".join(str(skill) for skill in skills) or "Not listed"
                else:
                    skill_text = compact(item.get("job_description"))[:250] or "Not listed"

                jobs.append(
                    {
                        "Job Title": compact(item.get("job_title")),
                        "Company": compact(item.get("employer_name")),
                        "Location": location_text,
                        "Salary": compact(item.get("job_salary")) or "Not listed",
                        "Source": source,
                        "Direct Apply Link": apply_link or "Not listed",
                        "Posted Date": item.get("job_posted_at_datetime_utc")
                        or item.get("job_posted_at_timestamp")
                        or "",
                        "Experience Required": compact(item.get("job_experience_in_place_of_education"))
                        or "Not listed",
                        "Required Skills": skill_text,
                        "Job Type (Remote / Hybrid / Onsite)": classify_job_type(location_text, compact(item.get("job_title"))),
                        "Job ID": compact(item.get("job_id")),
                        "Application Deadline": compact(item.get("job_offer_expiration_datetime_utc")) or "Not listed",
                        "_salary_min": item.get("job_min_salary"),
                        "_salary_max": item.get("job_max_salary"),
                        "_salary_currency": item.get("job_salary_currency") or "INR",
                        "_salary_period": item.get("job_salary_period") or "year",
                    }
                )

    return jobs


def normalize_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    title = compact(raw_job.get("Job Title"))
    company = compact(raw_job.get("Company"))
    if not title or not company:
        return None

    posted_dt = parse_datetime(raw_job.get("Posted Date"))
    if posted_dt is None:
        return None

    location = compact(raw_job.get("Location")) or "Not listed"
    skills = compact(raw_job.get("Required Skills")) or "Not listed"
    source = compact(raw_job.get("Source"))

    job_type = compact(raw_job.get("Job Type (Remote / Hybrid / Onsite)"))
    if not job_type or job_type == "Not listed":
        job_type = classify_job_type(location, title)

    normalized = {
        "Job Title": title,
        "Company": company,
        "Location": location,
        "Salary": display_salary(raw_job),
        "Source": source,
        "Direct Apply Link": compact(raw_job.get("Direct Apply Link")) or "Not listed",
        "Posted Date": format_iso(posted_dt),
        "Experience Required": compact(raw_job.get("Experience Required")) or "Not listed",
        "Required Skills": skills,
        "Job Type (Remote / Hybrid / Onsite)": job_type,
        "Job ID": compact(raw_job.get("Job ID")),
        "Application Deadline": compact(raw_job.get("Application Deadline")) or "Not listed",
        "_posted_dt": posted_dt,
        "_salary_lpa": salary_lpa(raw_job),
    }
    return normalized


def apply_filters(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    filtered: list[dict[str, Any]] = []

    for raw_job in jobs:
        job = normalize_job(raw_job)
        if job is None:
            continue

        if job["Source"] not in TARGET_SOURCES:
            continue
        if not keyword_matches(job["Job Title"], job["Required Skills"]):
            continue
        if not location_matches_constraint(job["Location"], job["Job Type (Remote / Hybrid / Onsite)"]):
            continue
        if now - job["_posted_dt"] > timedelta(hours=24):
            continue

        salary_value = job["_salary_lpa"]
        if salary_value is not None and salary_value < 6:
            continue

        filtered.append(job)

    filtered.sort(key=lambda item: item["_posted_dt"], reverse=True)

    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in filtered:
        dedupe_key = "|".join(
            [
                compact(job["Job Title"]).lower(),
                compact(job["Company"]).lower(),
                compact(job["Location"]).lower(),
            ]
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        deduped.append(job)

    final_jobs = []
    for job in deduped:
        output = {key: job.get(key, "Not listed") for key in JOB_COLUMNS}
        if not output["Salary"]:
            output["Salary"] = "Not listed"
        final_jobs.append(output)
    return final_jobs


def collect_jobs() -> list[dict[str, Any]]:
    all_jobs: list[dict[str, Any]] = []

    source_fetchers = [
        ("Indeed", fetch_indeed_jobs),
        ("RemoteOK", fetch_remoteok_jobs),
        ("YC Work at a Startup", fetch_yc_jobs),
        ("JSearch-backed boards", fetch_jsearch_jobs),
    ]

    for source_name, fetcher in source_fetchers:
        try:
            jobs = fetcher()
            print(f"[INFO] Collected {len(jobs)} jobs from {source_name}.")
            all_jobs.extend(jobs)
        except Exception as exc:
            print(f"[WARN] Source collector failed for {source_name}: {exc}")

    return all_jobs


def run(output_file: str, dump_json_file: str | None) -> None:
    all_jobs = collect_jobs()
    filtered_jobs = apply_filters(all_jobs)

    df = pd.DataFrame(filtered_jobs, columns=JOB_COLUMNS)
    df.to_excel(output_file, index=False)
    print(f"[INFO] Generated {output_file} with {len(filtered_jobs)} filtered jobs.")

    if dump_json_file:
        with open(dump_json_file, "w", encoding="utf-8") as handle:
            json.dump(filtered_jobs, handle, indent=2)
        print(f"[INFO] Wrote JSON dump to {dump_json_file}.")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily QA job monitor scraper.")
    parser.add_argument(
        "--output",
        default="jobs.xlsx",
        help="Output spreadsheet path (default: jobs.xlsx).",
    )
    parser.add_argument(
        "--dump-json",
        default=None,
        help="Optional path to dump filtered output as JSON.",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="No-op compatibility flag; email is handled by GitHub Actions.",
    )
    return parser


if __name__ == "__main__":
    cli_args = build_arg_parser().parse_args()
    run(output_file=cli_args.output, dump_json_file=cli_args.dump_json)
