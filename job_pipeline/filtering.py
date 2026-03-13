from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .constants import JOB_COLUMNS, TARGET_SOURCES
from .env_config import compact
from .normalization import (
    classify_job_type,
    display_salary,
    format_iso,
    keyword_matches,
    keyword_score,
    location_matches_constraint,
    location_quality_score,
    match_quality_label,
    normalize_location,
    parse_datetime,
    salary_lpa,
)


@dataclass
class FilterProfile:
    name: str
    max_age_hours: int
    relaxed_keywords: bool
    salary_floor_lpa: float | None


@dataclass
class FilterResult:
    strict_jobs: list[dict[str, Any]]
    relaxed_jobs: list[dict[str, Any]]
    source_health_rows: list[dict[str, Any]]
    diagnostics_rows: list[dict[str, Any]]


STRICT_PROFILE = FilterProfile(
    name="strict_24h",
    max_age_hours=24,
    relaxed_keywords=False,
    salary_floor_lpa=6.0,
)

RELAXED_PROFILE = FilterProfile(
    name="relaxed_7d",
    max_age_hours=24 * 7,
    relaxed_keywords=True,
    salary_floor_lpa=None,
)


def normalize_job(raw_job: dict[str, Any]) -> dict[str, Any] | None:
    title = compact(raw_job.get("Job Title"))
    company = compact(raw_job.get("Company"))
    if not title or not company:
        return None

    posted_dt = parse_datetime(raw_job.get("Posted Date"))
    if posted_dt is None:
        return None

    raw_location = compact(raw_job.get("Location")) or "Not listed"
    location = normalize_location(raw_location)
    skills = compact(raw_job.get("Required Skills")) or "Not listed"
    source = compact(raw_job.get("Source"))
    collector = compact(raw_job.get("_collector")) or source or "Unknown"

    job_type = compact(raw_job.get("Job Type (Remote / Hybrid / Onsite)"))
    if not job_type or job_type == "Not listed":
        job_type = classify_job_type(location, title)

    return {
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
        "_collector": collector,
        "_extra_text": compact(raw_job.get("_full_description")) or skills,
    }


def _confidence_score(
    job: dict[str, Any],
    *,
    now: datetime,
    profile: FilterProfile,
    keyword_points: int,
) -> float:
    age_hours = max(0.0, (now - job["_posted_dt"]).total_seconds() / 3600)
    freshness_component = max(0.0, 35.0 * (1.0 - (age_hours / float(profile.max_age_hours))))
    keyword_component = min(30.0, float(keyword_points))
    location_component = float(location_quality_score(job["Location"], job["Job Type (Remote / Hybrid / Onsite)"]))

    salary_component = 0.0
    if job["_salary_lpa"] is not None:
        salary_component = 15.0 if job["_salary_lpa"] >= 6.0 else 7.0

    source_component = 5.0 if job["Source"] in {"Company career pages", "YC Work at a Startup"} else 3.0
    score = freshness_component + keyword_component + location_component + salary_component + source_component
    return round(min(100.0, max(0.0, score)), 2)


def _dedupe_jobs(
    jobs: list[dict[str, Any]],
    *,
    reason_counts: Counter,
    source_health: dict[str, dict[str, Any]],
    profile: FilterProfile,
) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for job in jobs:
        dedupe_key = "|".join(
            [
                compact(job["Job Title"]).lower(),
                compact(job["Company"]).lower(),
                compact(job["Location"]).lower(),
            ]
        )
        if dedupe_key in seen:
            reason_counts["duplicate"] += 1
            source_health[job["_collector"]][f"{profile.name}_drop_duplicate"] += 1
            continue
        seen.add(dedupe_key)
        deduped.append(job)
    return deduped


def _to_output_rows(jobs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        output = {key: job.get(key, "Not listed") for key in JOB_COLUMNS}
        if not output["Salary"]:
            output["Salary"] = "Not listed"
        output["Confidence Score"] = job.get("Confidence Score", "0.00")
        output["Match Quality"] = job.get("Match Quality", "Low")
        rows.append(output)
    return rows


def _evaluate_profile(
    normalized_jobs: list[dict[str, Any]],
    *,
    profile: FilterProfile,
    now: datetime,
    source_health: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], Counter]:
    reason_counts = Counter()
    candidates: list[dict[str, Any]] = []
    candidate_key = f"{profile.name}_candidates"
    kept_key = f"{profile.name}_kept"

    for job in normalized_jobs:
        collector = job["_collector"]
        if job["Source"] not in TARGET_SOURCES:
            reason_counts["source_not_allowed"] += 1
            source_health[collector][f"{profile.name}_drop_source_not_allowed"] += 1
            continue

        keyword_points = keyword_score(
            title=job["Job Title"],
            skills=job["Required Skills"],
            extra_text=job["_extra_text"],
            relaxed=profile.relaxed_keywords,
        )
        if not keyword_matches(
            title=job["Job Title"],
            skills=job["Required Skills"],
            extra_text=job["_extra_text"],
            relaxed=profile.relaxed_keywords,
        ):
            reason_counts["keyword_mismatch"] += 1
            source_health[collector][f"{profile.name}_drop_keyword_mismatch"] += 1
            continue

        if not location_matches_constraint(job["Location"], job["Job Type (Remote / Hybrid / Onsite)"]):
            reason_counts["location_mismatch"] += 1
            source_health[collector][f"{profile.name}_drop_location_mismatch"] += 1
            continue

        if now - job["_posted_dt"] > timedelta(hours=profile.max_age_hours):
            age_reason = f"older_than_{profile.max_age_hours}h"
            reason_counts[age_reason] += 1
            source_health[collector][f"{profile.name}_drop_{age_reason}"] += 1
            continue

        salary_value = job["_salary_lpa"]
        if profile.salary_floor_lpa is not None and salary_value is not None and salary_value < profile.salary_floor_lpa:
            salary_reason = f"salary_below_{profile.salary_floor_lpa:g}_lpa"
            reason_counts[salary_reason] += 1
            source_health[collector][f"{profile.name}_drop_{salary_reason}"] += 1
            continue

        confidence = _confidence_score(job, now=now, profile=profile, keyword_points=keyword_points)
        scored_job = dict(job)
        scored_job["Confidence Score"] = f"{confidence:.2f}"
        scored_job["Match Quality"] = match_quality_label(confidence)
        scored_job["_confidence_score_num"] = confidence
        candidates.append(scored_job)
        source_health[collector][candidate_key] += 1

    candidates.sort(key=lambda item: (item["_confidence_score_num"], item["_posted_dt"]), reverse=True)
    deduped = _dedupe_jobs(
        candidates,
        reason_counts=reason_counts,
        source_health=source_health,
        profile=profile,
    )
    for job in deduped:
        source_health[job["_collector"]][kept_key] += 1
    return deduped, reason_counts


def apply_filters(
    jobs: list[dict[str, Any]],
    source_fetch_summary: dict[str, dict[str, Any]] | None = None,
) -> FilterResult:
    now = datetime.now(timezone.utc)
    source_fetch_summary = source_fetch_summary or {}

    source_health: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "fetched": 0,
            "fetch_errors": 0,
            "normalized": 0,
            "normalize_failed": 0,
            "strict_24h_candidates": 0,
            "strict_24h_kept": 0,
            "relaxed_7d_candidates": 0,
            "relaxed_7d_kept": 0,
            "strict_24h_drop_source_not_allowed": 0,
            "strict_24h_drop_keyword_mismatch": 0,
            "strict_24h_drop_location_mismatch": 0,
            "strict_24h_drop_older_than_24h": 0,
            "strict_24h_drop_salary_below_6_lpa": 0,
            "strict_24h_drop_duplicate": 0,
            "relaxed_7d_drop_source_not_allowed": 0,
            "relaxed_7d_drop_keyword_mismatch": 0,
            "relaxed_7d_drop_location_mismatch": 0,
            "relaxed_7d_drop_older_than_168h": 0,
            "relaxed_7d_drop_duplicate": 0,
        }
    )

    for collector, values in source_fetch_summary.items():
        source_health[collector]["fetched"] = int(values.get("fetched", 0))
        source_health[collector]["fetch_errors"] = int(values.get("fetch_errors", 0))

    normalized_jobs: list[dict[str, Any]] = []
    normalize_failed = 0
    for raw_job in jobs:
        collector = compact(raw_job.get("_collector")) or compact(raw_job.get("Source")) or "Unknown"
        job = normalize_job(raw_job)
        if job is None:
            source_health[collector]["normalize_failed"] += 1
            normalize_failed += 1
            continue
        source_health[job["_collector"]]["normalized"] += 1
        normalized_jobs.append(job)

    strict_jobs_internal, strict_reasons = _evaluate_profile(
        normalized_jobs,
        profile=STRICT_PROFILE,
        now=now,
        source_health=source_health,
    )
    relaxed_jobs_internal, relaxed_reasons = _evaluate_profile(
        normalized_jobs,
        profile=RELAXED_PROFILE,
        now=now,
        source_health=source_health,
    )

    strict_jobs = _to_output_rows(strict_jobs_internal)
    relaxed_jobs = _to_output_rows(relaxed_jobs_internal)

    source_health_rows: list[dict[str, Any]] = []
    for collector in sorted(source_health.keys()):
        metrics = source_health[collector]
        source_health_rows.append(
            {
                "Source Collector": collector,
                "Fetched": metrics["fetched"],
                "Fetch Errors": metrics["fetch_errors"],
                "Normalized": metrics["normalized"],
                "Normalize Failed": metrics["normalize_failed"],
                "Strict Candidates": metrics["strict_24h_candidates"],
                "Strict Kept": metrics["strict_24h_kept"],
                "Strict Drop Source": metrics["strict_24h_drop_source_not_allowed"],
                "Strict Drop Keyword": metrics["strict_24h_drop_keyword_mismatch"],
                "Strict Drop Location": metrics["strict_24h_drop_location_mismatch"],
                "Strict Drop Age": metrics["strict_24h_drop_older_than_24h"],
                "Strict Drop Salary": metrics["strict_24h_drop_salary_below_6_lpa"],
                "Strict Drop Duplicate": metrics["strict_24h_drop_duplicate"],
                "Relaxed Candidates": metrics["relaxed_7d_candidates"],
                "Relaxed Kept": metrics["relaxed_7d_kept"],
                "Relaxed Drop Source": metrics["relaxed_7d_drop_source_not_allowed"],
                "Relaxed Drop Keyword": metrics["relaxed_7d_drop_keyword_mismatch"],
                "Relaxed Drop Location": metrics["relaxed_7d_drop_location_mismatch"],
                "Relaxed Drop Age": metrics["relaxed_7d_drop_older_than_168h"],
                "Relaxed Drop Duplicate": metrics["relaxed_7d_drop_duplicate"],
            }
        )

    diagnostics_rows = [
        {"Profile": "strict_24h", "Metric": "input_jobs", "Value": len(jobs)},
        {"Profile": "strict_24h", "Metric": "normalized_jobs", "Value": len(normalized_jobs)},
        {"Profile": "strict_24h", "Metric": "normalize_failed", "Value": normalize_failed},
        {"Profile": "strict_24h", "Metric": "kept_jobs", "Value": len(strict_jobs)},
        {"Profile": "relaxed_7d", "Metric": "input_jobs", "Value": len(jobs)},
        {"Profile": "relaxed_7d", "Metric": "normalized_jobs", "Value": len(normalized_jobs)},
        {"Profile": "relaxed_7d", "Metric": "normalize_failed", "Value": normalize_failed},
        {"Profile": "relaxed_7d", "Metric": "kept_jobs", "Value": len(relaxed_jobs)},
    ]
    diagnostics_rows.extend(
        {"Profile": "strict_24h", "Metric": f"dropped:{reason}", "Value": count}
        for reason, count in sorted(strict_reasons.items())
    )
    diagnostics_rows.extend(
        {"Profile": "relaxed_7d", "Metric": f"dropped:{reason}", "Value": count}
        for reason, count in sorted(relaxed_reasons.items())
    )

    print("[INFO] Filter diagnostics:")
    print(f"  input={len(jobs)} normalized={len(normalized_jobs)} normalize_failed={normalize_failed}")
    print(f"  strict_24h_kept={len(strict_jobs)} relaxed_7d_kept={len(relaxed_jobs)}")
    if strict_reasons:
        print(f"  strict_drop_reasons={dict(strict_reasons)}")
    if relaxed_reasons:
        print(f"  relaxed_drop_reasons={dict(relaxed_reasons)}")

    return FilterResult(
        strict_jobs=strict_jobs,
        relaxed_jobs=relaxed_jobs,
        source_health_rows=source_health_rows,
        diagnostics_rows=diagnostics_rows,
    )
