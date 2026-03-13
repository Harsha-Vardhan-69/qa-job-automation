import argparse
import os
from collections import defaultdict
from typing import Callable

import pandas as pd

from .constants import JOB_COLUMNS, JSEARCH_MAPPED_SOURCES
from .env_config import (
    enable_lever_autodiscovery,
    env_value,
    initialize_environment,
    lever_discovery_urls,
    lever_sites,
)
from .filtering import FilterResult, apply_filters
from .lever_discovery import discover_lever_slugs
from .sources import (
    fetch_ashby_jobs,
    fetch_greenhouse_jobs,
    fetch_jsearch_jobs,
    fetch_lever_jobs,
    fetch_remoteok_jobs,
    fetch_smartrecruiters_jobs,
    fetch_workday_jobs,
    fetch_yc_jobs,
)

SourceFetcher = Callable[[], list[dict[str, object]]]


def _collector_summary_template() -> dict[str, int]:
    return {"fetched": 0, "fetch_errors": 0}


def _run_collector(
    collector_name: str,
    fetcher: SourceFetcher,
    all_jobs: list[dict[str, object]],
    source_fetch_summary: dict[str, dict[str, int]],
) -> None:
    try:
        jobs = fetcher()
        for job in jobs:
            job["_collector"] = collector_name
        all_jobs.extend(jobs)
        source_fetch_summary[collector_name]["fetched"] += len(jobs)
        print(f"[INFO] Collected {len(jobs)} jobs from {collector_name}.")
    except Exception as exc:
        source_fetch_summary[collector_name]["fetch_errors"] += 1
        print(f"[WARN] Source collector failed for {collector_name}: {exc}")


def collect_jobs() -> tuple[list[dict[str, object]], dict[str, dict[str, int]]]:
    all_jobs: list[dict[str, object]] = []
    source_fetch_summary: dict[str, dict[str, int]] = defaultdict(_collector_summary_template)
    use_lever_discovery = enable_lever_autodiscovery()

    direct_fetchers: list[tuple[str, SourceFetcher]] = [
        ("RemoteOK", fetch_remoteok_jobs),
        ("YC Work at a Startup", fetch_yc_jobs),
        ("Greenhouse company pages", fetch_greenhouse_jobs),
        ("Ashby company pages", fetch_ashby_jobs),
        ("SmartRecruiters company pages", fetch_smartrecruiters_jobs),
        ("Workday company pages", fetch_workday_jobs),
    ]
    for source_name, fetcher in direct_fetchers:
        _run_collector(source_name, fetcher, all_jobs, source_fetch_summary)

    configured_sites = lever_sites()
    discovered_sites: list[str] = []
    if use_lever_discovery:
        discovered_sites = discover_lever_slugs(
            jobs=all_jobs,
            seed_urls=lever_discovery_urls(),
        )
        if discovered_sites:
            print(f"[INFO] Lever auto-discovery found {len(discovered_sites)} site slug(s).")
        else:
            print("[INFO] Lever auto-discovery found no additional site slugs.")
    else:
        print("[INFO] Lever auto-discovery disabled (ENABLE_LEVER_AUTODISCOVERY=false).")

    lever_candidates = list(dict.fromkeys([*configured_sites, *discovered_sites]))
    if lever_candidates:
        print(f"[INFO] Lever collector will query {len(lever_candidates)} site slug(s).")
    else:
        print("[INFO] Lever collector has no site slugs to query.")

    _run_collector(
        "Lever company pages",
        lambda: fetch_lever_jobs(sites_override=lever_candidates),
        all_jobs,
        source_fetch_summary,
    )

    if env_value("RAPIDAPI_KEY"):
        _run_collector(
            "JSearch-backed boards (LinkedIn/Naukri/Indeed/Glassdoor/etc.)",
            fetch_jsearch_jobs,
            all_jobs,
            source_fetch_summary,
        )
    else:
        disabled = ", ".join(JSEARCH_MAPPED_SOURCES)
        print("[INFO] JSearch skipped because RAPIDAPI_KEY is not set.")
        print(f"[INFO] Disabled direct-scrape sources in this mode: {disabled}")
        print("[INFO] Reason: these boards are rate-limited or bot-protected without API/proxy access.")

    return all_jobs, dict(source_fetch_summary)


def _write_report(output_file: str, filter_result: FilterResult) -> None:
    strict_df = pd.DataFrame(filter_result.strict_jobs, columns=JOB_COLUMNS)
    relaxed_df = pd.DataFrame(filter_result.relaxed_jobs, columns=JOB_COLUMNS)
    source_health_df = pd.DataFrame(filter_result.source_health_rows)
    diagnostics_df = pd.DataFrame(filter_result.diagnostics_rows)

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        strict_df.to_excel(writer, index=False, sheet_name="Strict_24h")
        relaxed_df.to_excel(writer, index=False, sheet_name="Relaxed_7d")
        source_health_df.to_excel(writer, index=False, sheet_name="Source_Health")
        diagnostics_df.to_excel(writer, index=False, sheet_name="Diagnostics")


def run_pipeline(output_file: str) -> None:
    initialize_environment()

    all_jobs, source_fetch_summary = collect_jobs()
    filter_result = apply_filters(all_jobs, source_fetch_summary=source_fetch_summary)

    output_dir = os.path.dirname(output_file)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    _write_report(output_file=output_file, filter_result=filter_result)
    print(
        f"[INFO] Generated {output_file} with "
        f"{len(filter_result.strict_jobs)} strict and {len(filter_result.relaxed_jobs)} relaxed jobs."
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Daily QA job monitor scraper.")
    parser.add_argument(
        "--output",
        default="artifacts/jobs.xlsx",
        help="Output spreadsheet path (default: artifacts/jobs.xlsx).",
    )
    parser.add_argument(
        "--skip-email",
        action="store_true",
        help="No-op compatibility flag; email is handled by GitHub Actions.",
    )
    return parser
