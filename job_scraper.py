#!/usr/bin/env python3
"""Daily QA job aggregator.

Collects jobs from configured sources, applies strict filters, exports jobs.xlsx,
and optionally emails the spreadsheet.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests
from dateutil import parser as dt_parser

KEYWORDS = [
    "QA Tester",
    "Quality Assurance Engineer",
    "Software Test Engineer",
    "SDET",
    "QA Analyst",
    "Test Automation Engineer",
    "Selenium Automation Engineer",
]

LOCATION_KEYWORDS = [
    "hyderabad",
    "bangalore",
    "bengaluru",
    "remote india",
    "india remote",
    "global remote",
    "remote",
]

ALLOWED_PUBLISHERS = {
    "linkedin",
    "naukri",
    "indeed",
    "glassdoor",
    "wellfound",
    "instahyre",
    "cutshort",
    "hirist",
    "work at a startup",
    "yc",
    "remoteok",
    "company",
}


@dataclass
class JobRecord:
    job_title: str
    company: str
    location: str
    salary: str
    source: str
    direct_apply_link: str
    posted_date: str
    experience_required: str
    required_skills: str
    job_type: str
    job_id: str
    application_deadline: str

    def dedupe_key(self) -> str:
        return "|".join(
            [
                normalize(self.job_title),
                normalize(self.company),
                normalize(self.location),
            ]
        )


def normalize(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc) if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        dt = dt_parser.parse(str(value))
        return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError, OverflowError):
        return None


def extract_salary_lpa(salary_text: str) -> float | None:
    if not salary_text:
        return None
    text = salary_text.lower()
    nums = [float(x) for x in re.findall(r"\d+(?:\.\d+)?", text)]
    if not nums:
        return None

    # LPA style
    if "lpa" in text or "lak" in text or "lakh" in text:
        return max(nums)

    # annual INR style
    if "₹" in text or "inr" in text or "rs" in text:
        return max(nums) / 100000

    # USD approximate to INR LPA at 83 INR/USD
    if "$" in text or "usd" in text:
        return (max(nums) * 83) / 100000

    return None


def match_keywords(title: str, description: str) -> bool:
    content = normalize(f"{title} {description}")
    return any(normalize(k) in content for k in KEYWORDS)


def match_location(location: str) -> bool:
    loc = normalize(location)
    return any(key in loc for key in LOCATION_KEYWORDS)


def infer_job_type(location: str) -> str:
    loc = normalize(location)
    if "remote" in loc:
        return "Remote"
    if "hybrid" in loc:
        return "Hybrid"
    return "Onsite"


def format_date(dt: datetime | None) -> str:
    if not dt:
        return "Not listed"
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def fetch_jsearch_jobs(rapidapi_key: str) -> list[dict[str, Any]]:
    endpoint = "https://jsearch.p.rapidapi.com/search"
    headers = {
        "X-RapidAPI-Key": rapidapi_key,
        "X-RapidAPI-Host": "jsearch.p.rapidapi.com",
    }
    rows: list[dict[str, Any]] = []

    for keyword in KEYWORDS:
        for location in ["Hyderabad", "Bangalore", "Remote India", "Global Remote"]:
            params = {"query": f"{keyword} in {location}", "page": "1", "num_pages": "1", "date_posted": "all"}
            response = requests.get(endpoint, headers=headers, params=params, timeout=30)
            response.raise_for_status()
            payload = response.json()
            rows.extend(payload.get("data", []))

    return rows


def map_jsearch(row: dict[str, Any]) -> JobRecord | None:
    publisher = normalize(row.get("job_publisher", ""))
    if publisher and not any(p in publisher for p in ALLOWED_PUBLISHERS):
        return None

    posted = parse_datetime(row.get("job_posted_at_datetime_utc") or row.get("job_posted_at_datetime"))
    salary_min = row.get("job_min_salary")
    salary_max = row.get("job_max_salary")
    salary_period = row.get("job_salary_period")

    salary = "Not listed"
    if salary_min or salary_max:
        salary = f"{salary_min or ''}-{salary_max or ''} {salary_period or ''}".strip()

    return JobRecord(
        job_title=row.get("job_title") or "",
        company=row.get("employer_name") or "Unknown",
        location=row.get("job_city") or row.get("job_country") or "",
        salary=salary,
        source=row.get("job_publisher") or "Unknown",
        direct_apply_link=row.get("job_apply_link") or row.get("job_google_link") or "",
        posted_date=format_date(posted),
        experience_required=str(row.get("job_required_experience", {}).get("required_experience_in_months") or "Not listed"),
        required_skills=", ".join(row.get("job_highlights", {}).get("Qualifications", [])[:8]) or "Not listed",
        job_type=infer_job_type(row.get("job_employment_type") or row.get("job_city") or ""),
        job_id=row.get("job_id") or "",
        application_deadline="Not listed",
    )


def fetch_remoteok_jobs() -> list[dict[str, Any]]:
    response = requests.get("https://remoteok.com/api", headers={"User-Agent": "qa-job-automation"}, timeout=30)
    response.raise_for_status()
    data = response.json()
    return [r for r in data if isinstance(r, dict) and r.get("id")]


def map_remoteok(row: dict[str, Any]) -> JobRecord:
    posted = parse_datetime(row.get("date"))
    return JobRecord(
        job_title=row.get("position") or "",
        company=row.get("company") or "Unknown",
        location=row.get("location") or "Global Remote",
        salary="Not listed",
        source="RemoteOK",
        direct_apply_link=row.get("url") or "",
        posted_date=format_date(posted),
        experience_required="Not listed",
        required_skills=", ".join(row.get("tags") or []) or "Not listed",
        job_type="Remote",
        job_id=str(row.get("id") or ""),
        application_deadline="Not listed",
    )


def fetch_yc_jobs() -> list[dict[str, Any]]:
    response = requests.get("https://www.workatastartup.com/job_listings.json", timeout=30)
    response.raise_for_status()
    payload = response.json()
    return payload.get("jobs", [])


def map_yc(row: dict[str, Any]) -> JobRecord:
    posted = parse_datetime(row.get("updatedAt") or row.get("createdAt"))
    return JobRecord(
        job_title=row.get("title") or "",
        company=(row.get("startup") or {}).get("name") or "Unknown",
        location=row.get("location") or "Global Remote",
        salary="Not listed",
        source="YC Work at a Startup",
        direct_apply_link=f"https://www.workatastartup.com/jobs/{row.get('id')}",
        posted_date=format_date(posted),
        experience_required="Not listed",
        required_skills=", ".join(row.get("skills") or []) or "Not listed",
        job_type=infer_job_type(row.get("location") or ""),
        job_id=str(row.get("id") or ""),
        application_deadline="Not listed",
    )


def apply_filters(records: Iterable[JobRecord]) -> list[JobRecord]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)

    result: list[JobRecord] = []
    seen: set[str] = set()

    for rec in records:
        if not rec.job_title or not rec.direct_apply_link:
            continue
        if not match_keywords(rec.job_title, rec.required_skills):
            continue
        if not match_location(rec.location):
            continue

        posted = parse_datetime(rec.posted_date)
        if posted and posted < cutoff:
            continue

        parsed_lpa = extract_salary_lpa(rec.salary)
        if parsed_lpa is not None and parsed_lpa < 6:
            continue
        if parsed_lpa is None:
            rec.salary = "Not listed"

        key = rec.dedupe_key()
        if key in seen:
            continue
        seen.add(key)
        result.append(rec)

    result.sort(key=lambda x: parse_datetime(x.posted_date) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return result


def write_excel(records: list[JobRecord], output: Path) -> None:
    df = pd.DataFrame(
        [
            {
                "Job Title": r.job_title,
                "Company": r.company,
                "Location": r.location,
                "Salary": r.salary,
                "Source": r.source,
                "Direct Apply Link": r.direct_apply_link,
                "Posted Date": r.posted_date,
                "Experience Required": r.experience_required,
                "Required Skills": r.required_skills,
                "Job Type (Remote / Hybrid / Onsite)": r.job_type,
                "Job ID": r.job_id,
                "Application Deadline": r.application_deadline,
            }
            for r in records
        ]
    )
    df.to_excel(output, index=False)


def send_email(attachment_path: Path, recipient: str) -> None:
    smtp_host = os.getenv("SMTP_HOST")
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")
    sender = os.getenv("EMAIL_FROM", smtp_user or "")

    if not all([smtp_host, smtp_user, smtp_password, sender]):
        raise RuntimeError("Missing SMTP configuration. Set SMTP_HOST/SMTP_USER/SMTP_PASSWORD/EMAIL_FROM.")

    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = recipient
    msg["Subject"] = "Daily QA Jobs Report"
    msg.set_content("Attached is the daily QA job report.")

    msg.add_attachment(
        attachment_path.read_bytes(),
        maintype="application",
        subtype="vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=attachment_path.name,
    )

    with smtplib.SMTP(smtp_host, smtp_port) as smtp:
        smtp.starttls()
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(msg)


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect QA jobs and generate daily report")
    parser.add_argument("--output", default="jobs.xlsx", help="Output Excel file path")
    parser.add_argument("--recipient", default=os.getenv("REPORT_RECIPIENT", "harshavardhanvallabhaneni@gmail.com"))
    parser.add_argument("--skip-email", action="store_true", help="Skip email delivery")
    parser.add_argument("--dump-json", default="", help="Optional path to dump filtered jobs JSON")
    args = parser.parse_args()

    all_records: list[JobRecord] = []

    rapidapi_key = os.getenv("RAPIDAPI_KEY", "").strip()
    if rapidapi_key:
        try:
            all_records.extend(filter(None, (map_jsearch(row) for row in fetch_jsearch_jobs(rapidapi_key))))
        except Exception as exc:
            print(f"[WARN] JSearch source failed: {exc}")
    else:
        print("[WARN] RAPIDAPI_KEY not set; skipping LinkedIn/Naukri/Indeed/Glassdoor-like source via JSearch.")

    try:
        all_records.extend(map_remoteok(row) for row in fetch_remoteok_jobs())
    except Exception as exc:
        print(f"[WARN] RemoteOK source failed: {exc}")

    try:
        all_records.extend(map_yc(row) for row in fetch_yc_jobs())
    except Exception as exc:
        print(f"[WARN] YC source failed: {exc}")

    filtered = apply_filters(all_records)
    output = Path(args.output)
    write_excel(filtered, output)
    print(f"Generated {output} with {len(filtered)} jobs.")

    if args.dump_json:
        Path(args.dump_json).write_text(json.dumps([r.__dict__ for r in filtered], indent=2), encoding="utf-8")

    if not args.skip_email:
        send_email(output, args.recipient)
        print(f"Email sent to {args.recipient}.")


if __name__ == "__main__":
    main()
