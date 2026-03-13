from __future__ import annotations

import html
import json
import re
from typing import Any
from urllib.parse import urlparse

from .constants import KEYWORDS, LOCATION_QUERIES, TARGET_SOURCES
from .env_config import (
    ashby_orgs,
    compact,
    env_value,
    greenhouse_boards,
    jsearch_request_config,
    lever_sites,
    smartrecruiters_companies,
    smartrecruiters_max_pages,
    workday_api_urls,
    workday_max_pages,
)
from .http_client import get_json, get_text, post_json
from .normalization import classify_job_type


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


def _plain_text_from_html(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    return compact(text)


def _dedupe_sites(values: list[str], case_insensitive: bool = True) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        cleaned = compact(value)
        key = cleaned.lower() if case_insensitive else cleaned
        if not cleaned or key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned if not case_insensitive else key)
    return deduped


def fetch_remoteok_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    try:
        payload = get_json("https://remoteok.com/api")
    except Exception as exc:
        print(f"[WARN] RemoteOK fetch failed: {exc}")
        return jobs

    if not isinstance(payload, list):
        return jobs

    for item in payload:
        if not isinstance(item, dict) or "position" not in item:
            continue

        full_text = ", ".join(item.get("tags") or [])
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
                "Required Skills": full_text[:300] or "Not listed",
                "Job Type (Remote / Hybrid / Onsite)": "Remote",
                "Job ID": str(item.get("id") or ""),
                "Application Deadline": "Not listed",
                "_salary_min": item.get("salary_min"),
                "_salary_max": item.get("salary_max"),
                "_salary_currency": "USD",
                "_salary_period": "year",
                "_full_description": full_text,
            }
        )

    return jobs


def _greenhouse_salary_from_metadata(metadata: Any) -> str:
    if not isinstance(metadata, list):
        return "Not listed"

    for item in metadata:
        if not isinstance(item, dict):
            continue
        name = compact(item.get("name")).lower()
        if not name:
            continue
        if any(token in name for token in ("salary", "compensation", "ctc", "base pay", "pay range")):
            value_text = compact(item.get("value"))
            if value_text and value_text.lower() not in {"true", "false"}:
                return value_text
    return "Not listed"


def _job_type_from_greenhouse_metadata(location: str, title: str, metadata: Any) -> str:
    if isinstance(metadata, list):
        for item in metadata:
            if not isinstance(item, dict):
                continue
            name = compact(item.get("name")).lower()
            if "workplace" in name or "workplace type" in name or "location type" in name:
                value = compact(item.get("value")).lower()
                if "remote" in value:
                    return "Remote"
                if "hybrid" in value:
                    return "Hybrid"
                if "onsite" in value or "on-site" in value:
                    return "Onsite"
    return classify_job_type(location, title)


def fetch_greenhouse_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    boards = greenhouse_boards()
    if not boards:
        print("[INFO] Greenhouse source enabled but no board tokens configured.")
        return jobs

    for board in boards:
        endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs"
        try:
            payload = get_json(endpoint, params={"content": "true"})
        except Exception as exc:
            print(f"[WARN] Greenhouse fetch failed for board '{board}': {exc}")
            continue

        data = payload.get("jobs", []) if isinstance(payload, dict) else []
        for item in data:
            if not isinstance(item, dict):
                continue

            title = compact(item.get("title"))
            company = compact(item.get("company_name")) or board
            if not title or not company:
                continue

            location = compact((item.get("location") or {}).get("name")) or "Not listed"
            metadata = item.get("metadata")
            full_text = _plain_text_from_html(item.get("content"))
            posted_date = item.get("first_published") or item.get("updated_at") or ""
            salary_text = _greenhouse_salary_from_metadata(metadata)

            jobs.append(
                {
                    "Job Title": title,
                    "Company": company,
                    "Location": location,
                    "Salary": salary_text,
                    "Source": "Company career pages",
                    "Direct Apply Link": compact(item.get("absolute_url")) or "Not listed",
                    "Posted Date": posted_date,
                    "Experience Required": "Not listed",
                    "Required Skills": full_text[:300] or "Not listed",
                    "Job Type (Remote / Hybrid / Onsite)": _job_type_from_greenhouse_metadata(location, title, metadata),
                    "Job ID": str(item.get("id") or ""),
                    "Application Deadline": "Not listed",
                    "_full_description": full_text,
                }
            )

    return jobs


def _job_type_from_lever_posting(location: str, title: str, posting: dict[str, Any]) -> str:
    categories = posting.get("categories") or {}
    workplace_hint = " ".join(
        [
            compact(categories.get("location")),
            compact(categories.get("commitment")),
            compact(categories.get("team")),
        ]
    ).lower()
    if "remote" in workplace_hint:
        return "Remote"
    if "hybrid" in workplace_hint:
        return "Hybrid"
    return classify_job_type(location, title)


def fetch_lever_jobs(sites_override: list[str] | None = None) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    sites = _dedupe_sites(sites_override or lever_sites())
    if not sites:
        print("[INFO] Lever source enabled but no site slugs configured.")
        return jobs

    for site in sites:
        endpoint = f"https://api.lever.co/v0/postings/{site}"
        try:
            payload = get_json(endpoint, params={"mode": "json"})
        except Exception as exc:
            print(f"[WARN] Lever fetch failed for site '{site}': {exc}")
            continue

        if not isinstance(payload, list):
            continue

        for item in payload:
            if not isinstance(item, dict):
                continue

            title = compact(item.get("text"))
            if not title:
                continue

            categories = item.get("categories") or {}
            location = compact(categories.get("location")) or "Not listed"
            full_text = compact(item.get("descriptionPlain") or item.get("description"))

            salary_range = item.get("salaryRange") if isinstance(item.get("salaryRange"), dict) else {}
            min_salary = salary_range.get("min")
            max_salary = salary_range.get("max")
            salary_currency = compact(salary_range.get("currency") or salary_range.get("currencyCode")) or "USD"
            salary_period = compact(salary_range.get("interval")) or "year"

            jobs.append(
                {
                    "Job Title": title,
                    "Company": compact(item.get("company")) or site,
                    "Location": location,
                    "Salary": compact(item.get("salaryDescription")) or "Not listed",
                    "Source": "Company career pages",
                    "Direct Apply Link": compact(item.get("hostedUrl")) or "Not listed",
                    "Posted Date": item.get("createdAt") or "",
                    "Experience Required": "Not listed",
                    "Required Skills": full_text[:300] or "Not listed",
                    "Job Type (Remote / Hybrid / Onsite)": _job_type_from_lever_posting(location, title, item),
                    "Job ID": compact(item.get("id")),
                    "Application Deadline": "Not listed",
                    "_salary_min": min_salary,
                    "_salary_max": max_salary,
                    "_salary_currency": salary_currency,
                    "_salary_period": salary_period,
                    "_full_description": full_text,
                }
            )

    return jobs


def _extract_ashby_app_data(page_text: str) -> dict[str, Any] | None:
    needle = "window.__appData = "
    start = page_text.find(needle)
    if start < 0:
        return None
    json_start = start + len(needle)
    braces = 0
    end = None
    for index, char in enumerate(page_text[json_start:], json_start):
        if char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
            if braces == 0:
                end = index + 1
                break
    if end is None:
        return None
    try:
        return json.loads(page_text[json_start:end])
    except Exception:
        return None


def fetch_ashby_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    orgs = _dedupe_sites(ashby_orgs())
    if not orgs:
        print("[INFO] Ashby source enabled but no org slugs configured.")
        return jobs

    for org in orgs:
        board_url = f"https://jobs.ashbyhq.com/{org}"
        try:
            page_text = get_text(board_url)
        except Exception as exc:
            print(f"[WARN] Ashby fetch failed for org '{org}': {exc}")
            continue

        app_data = _extract_ashby_app_data(page_text)
        if not isinstance(app_data, dict):
            print(f"[WARN] Ashby payload parse failed for org '{org}'.")
            continue

        org_name = compact((app_data.get("organization") or {}).get("name")) or org
        postings = (app_data.get("jobBoard") or {}).get("jobPostings") or []
        if not isinstance(postings, list):
            continue

        for item in postings:
            if not isinstance(item, dict):
                continue

            title = compact(item.get("title"))
            if not title:
                continue

            job_id = compact(item.get("id"))
            location = compact(item.get("locationName")) or "Not listed"
            workplace = compact(item.get("workplaceType"))
            employment = compact(item.get("employmentType"))
            department = compact(item.get("departmentName"))
            team = compact(item.get("teamName"))
            compensation = compact(item.get("compensationTierSummary")) or "Not listed"
            full_text = " ".join(part for part in [department, team, employment, workplace, compensation] if part)

            jobs.append(
                {
                    "Job Title": title,
                    "Company": org_name,
                    "Location": location,
                    "Salary": compensation,
                    "Source": "Company career pages",
                    "Direct Apply Link": f"{board_url}?jobId={compact(item.get('jobId') or job_id)}",
                    "Posted Date": item.get("updatedAt") or item.get("publishedDate") or "",
                    "Experience Required": "Not listed",
                    "Required Skills": full_text[:300] or "Not listed",
                    "Job Type (Remote / Hybrid / Onsite)": classify_job_type(f"{location} {workplace}", title),
                    "Job ID": job_id,
                    "Application Deadline": compact(item.get("applicationDeadline")) or "Not listed",
                    "_full_description": full_text,
                }
            )

    return jobs


def fetch_smartrecruiters_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    companies = _dedupe_sites(smartrecruiters_companies())
    if not companies:
        print("[INFO] SmartRecruiters source enabled but no company slugs configured.")
        return jobs

    limit = 100
    max_pages = smartrecruiters_max_pages()
    for company in companies:
        offset = 0
        pages = 0
        while pages < max_pages:
            endpoint = f"https://api.smartrecruiters.com/v1/companies/{company}/postings"
            try:
                payload = get_json(endpoint, params={"limit": str(limit), "offset": str(offset)})
            except Exception as exc:
                print(f"[WARN] SmartRecruiters fetch failed for company '{company}': {exc}")
                break

            content = payload.get("content", []) if isinstance(payload, dict) else []
            if not isinstance(content, list) or not content:
                break

            for item in content:
                if not isinstance(item, dict):
                    continue
                title = compact(item.get("name"))
                if not title:
                    continue

                location = compact((item.get("location") or {}).get("fullLocation")) or "Not listed"
                department = compact((item.get("department") or {}).get("label"))
                function = compact((item.get("function") or {}).get("label"))
                experience = compact((item.get("experienceLevel") or {}).get("label")) or "Not listed"
                employment = compact((item.get("typeOfEmployment") or {}).get("label"))
                full_text = " ".join(part for part in [department, function, experience, employment] if part)

                jobs.append(
                    {
                        "Job Title": title,
                        "Company": compact((item.get("company") or {}).get("name")) or company,
                        "Location": location,
                        "Salary": "Not listed",
                        "Source": "Company career pages",
                        "Direct Apply Link": f"https://jobs.smartrecruiters.com/{company}/{compact(item.get('id'))}",
                        "Posted Date": item.get("releasedDate") or "",
                        "Experience Required": experience,
                        "Required Skills": full_text[:300] or "Not listed",
                        "Job Type (Remote / Hybrid / Onsite)": classify_job_type(location, title),
                        "Job ID": compact(item.get("id")),
                        "Application Deadline": "Not listed",
                        "_full_description": full_text,
                    }
                )

            pages += 1
            offset += limit

    return jobs


def _workday_company_name(api_url: str) -> str:
    parsed = urlparse(api_url)
    host = parsed.netloc.split(":")[0]
    if not host:
        return "Workday"
    parts = host.split(".")
    return parts[0] if parts else host


def _workday_apply_url(api_url: str, external_path: str) -> str:
    parsed = urlparse(api_url)
    if not external_path:
        return api_url
    root = f"{parsed.scheme}://{parsed.netloc}"
    return f"{root}/{external_path.lstrip('/')}"


def fetch_workday_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    api_urls = _dedupe_sites(workday_api_urls(), case_insensitive=False)
    if not api_urls:
        print("[INFO] Workday source enabled but no API URLs configured.")
        return jobs

    max_pages = workday_max_pages()
    for raw_url in api_urls:
        endpoint = raw_url.rstrip("/")
        if not endpoint.endswith("/jobs"):
            endpoint = f"{endpoint}/jobs"

        company = _workday_company_name(endpoint)
        offset = 0
        limit = 50
        pages = 0
        while pages < max_pages:
            payload_body = {"appliedFacets": {}, "limit": limit, "offset": offset, "searchText": ""}
            try:
                payload = post_json(
                    endpoint,
                    json_body=payload_body,
                    headers={"Content-Type": "application/json"},
                )
            except Exception as exc:
                print(f"[WARN] Workday fetch failed for '{endpoint}': {exc}")
                break

            postings = payload.get("jobPostings") if isinstance(payload, dict) else None
            if not isinstance(postings, list) or not postings:
                break

            for item in postings:
                if not isinstance(item, dict):
                    continue
                title = compact(item.get("title") or item.get("bulletinTitle"))
                if not title:
                    continue

                location = compact(item.get("locationsText"))
                if not location:
                    bullet_fields = item.get("bulletFields")
                    if isinstance(bullet_fields, list) and bullet_fields:
                        location = compact(bullet_fields[0])
                location = location or "Not listed"

                description_tokens = []
                bullet_fields = item.get("bulletFields")
                if isinstance(bullet_fields, list):
                    description_tokens.extend(compact(field) for field in bullet_fields if compact(field))
                full_text = " ".join(description_tokens)

                jobs.append(
                    {
                        "Job Title": title,
                        "Company": company,
                        "Location": location,
                        "Salary": "Not listed",
                        "Source": "Company career pages",
                        "Direct Apply Link": _workday_apply_url(endpoint, compact(item.get("externalPath"))),
                        "Posted Date": compact(item.get("postedOn")).replace("Posted ", ""),
                        "Experience Required": "Not listed",
                        "Required Skills": full_text[:300] or "Not listed",
                        "Job Type (Remote / Hybrid / Onsite)": classify_job_type(location, title),
                        "Job ID": compact(item.get("bulletinID") or item.get("id")),
                        "Application Deadline": "Not listed",
                        "_full_description": full_text,
                    }
                )

            offset += limit
            pages += 1

    return jobs


def fetch_yc_jobs() -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    endpoint = "https://www.workatastartup.com/jobs"
    try:
        page_text = get_text(endpoint)
    except Exception as exc:
        print(f"[WARN] YC Work at a Startup fetch failed: {exc}")
        return jobs

    match = re.search(r'data-page=\"([^\"]+)\"', page_text)
    if not match:
        print("[WARN] YC Work at a Startup page payload not found.")
        return jobs

    try:
        payload = json.loads(html.unescape(match.group(1)))
    except Exception as exc:
        print(f"[WARN] YC Work at a Startup payload parse failed: {exc}")
        return jobs

    candidates = payload.get("props", {}).get("jobs", [])
    if not isinstance(candidates, list):
        print("[WARN] YC Work at a Startup jobs payload format changed.")
        return jobs

    seen_ids: set[str] = set()
    for item in candidates:
        if not isinstance(item, dict):
            continue

        title = compact(item.get("title"))
        company = compact(item.get("companyName"))
        if not title or not company:
            continue

        job_id = str(item.get("id") or "")
        if job_id and job_id in seen_ids:
            continue
        if job_id:
            seen_ids.add(job_id)

        company_slug = compact(item.get("companySlug"))
        apply_link = compact(item.get("applyUrl"))
        if apply_link and apply_link.startswith("/"):
            apply_link = f"https://www.workatastartup.com{apply_link}"
        elif not apply_link and company_slug and job_id:
            apply_link = f"https://www.workatastartup.com/companies/{company_slug}/jobs/{job_id}"

        location = compact(item.get("location")) or "Not listed"
        role_type = compact(item.get("roleType")) or "Not listed"
        full_text = f"{role_type} {compact(item.get('jobType'))}"

        jobs.append(
            {
                "Job Title": title,
                "Company": company,
                "Location": location,
                "Salary": "Not listed",
                "Source": "YC Work at a Startup",
                "Direct Apply Link": apply_link or "Not listed",
                # WAAS exposes company activity age; we use this as the best available recency proxy.
                "Posted Date": item.get("companyLastActiveAt") or "",
                "Experience Required": "Not listed",
                "Required Skills": role_type,
                "Job Type (Remote / Hybrid / Onsite)": classify_job_type(location, title),
                "Job ID": job_id,
                "Application Deadline": "Not listed",
                "_full_description": full_text,
            }
        )

    if not jobs:
        print("[WARN] YC Work at a Startup page had no parseable jobs.")
    return jobs


def fetch_jsearch_jobs() -> list[dict[str, Any]]:
    api_key = env_value("RAPIDAPI_KEY")
    if not api_key:
        print("[WARN] RAPIDAPI_KEY not set. Skipping JSearch-backed sources.")
        return []

    jobs: list[dict[str, Any]] = []
    endpoint = "https://jsearch.p.rapidapi.com/search"
    query_config = jsearch_request_config()

    headers = {
        "Content-Type": "application/json",
        "x-rapidapi-key": api_key,
        "x-rapidapi-host": "jsearch.p.rapidapi.com",
    }

    for keyword in KEYWORDS:
        for location in LOCATION_QUERIES:
            query = f"{keyword} in {location}"
            params = {
                "query": query,
                "page": query_config["page"],
                "num_pages": query_config["num_pages"],
                "country": query_config["country"],
                "date_posted": query_config["date_posted"],
            }
            try:
                payload = get_json(endpoint, headers=headers, params=params)
                data = payload.get("data", []) if isinstance(payload, dict) else []
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
                    full_text = skill_text
                else:
                    full_text = compact(item.get("job_description")) or "Not listed"
                    skill_text = full_text[:300]

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
                        "Required Skills": skill_text or "Not listed",
                        "Job Type (Remote / Hybrid / Onsite)": classify_job_type(
                            location_text,
                            compact(item.get("job_title")),
                        ),
                        "Job ID": compact(item.get("job_id")),
                        "Application Deadline": compact(item.get("job_offer_expiration_datetime_utc")) or "Not listed",
                        "_salary_min": item.get("job_min_salary"),
                        "_salary_max": item.get("job_max_salary"),
                        "_salary_currency": item.get("job_salary_currency") or "INR",
                        "_salary_period": item.get("job_salary_period") or "year",
                        "_full_description": full_text,
                    }
                )

    return jobs
