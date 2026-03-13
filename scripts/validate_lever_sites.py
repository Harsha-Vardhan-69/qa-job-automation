#!/usr/bin/env python3
"""Validate Lever site slugs and summarize QA-like coverage."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from job_pipeline.env_config import initialize_environment, lever_discovery_urls, lever_sites
from job_pipeline.lever_discovery import discover_slugs_from_seed_urls

QA_PATTERNS = [
    re.compile(r"\bqa\b"),
    re.compile(r"quality assurance"),
    re.compile(r"\bsdet\b"),
    re.compile(r"software test"),
    re.compile(r"test automation"),
    re.compile(r"selenium"),
    re.compile(r"engineer in test"),
    re.compile(r"test engineer"),
    re.compile(r"testing engineer"),
    re.compile(r"qa engineer"),
    re.compile(r"qa analyst"),
]


@dataclass
class SiteResult:
    slug: str
    valid: bool
    status_code: int | None = None
    jobs: int = 0
    qa_like_jobs: int = 0
    reason: str = ""


def _split_csv(raw: str) -> list[str]:
    return [part.strip() for part in raw.split(",") if part.strip()]


def _load_sites_from_file(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    slugs: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if "," in text:
            slugs.extend(_split_csv(text))
        else:
            slugs.append(text)
    return slugs


def _is_qa_like(posting: dict[str, Any]) -> bool:
    categories = posting.get("categories") or {}
    haystack = " ".join(
        [
            str(posting.get("text") or ""),
            str(categories.get("team") or ""),
            str(categories.get("commitment") or ""),
            str(categories.get("location") or ""),
            str(posting.get("descriptionPlain") or ""),
        ]
    ).lower()
    return any(pattern.search(haystack) for pattern in QA_PATTERNS)


def validate_site(slug: str, timeout: int) -> SiteResult:
    endpoint = f"https://api.lever.co/v0/postings/{slug}"
    try:
        response = requests.get(
            endpoint,
            params={"mode": "json"},
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=timeout,
        )
    except Exception as exc:
        return SiteResult(slug=slug, valid=False, reason=f"request_error: {exc}")

    if response.status_code != 200:
        body = response.text.strip().replace("\n", " ")
        snippet = body[:120] if body else "empty response"
        return SiteResult(
            slug=slug,
            valid=False,
            status_code=response.status_code,
            reason=f"http_{response.status_code}: {snippet}",
        )

    try:
        payload = response.json()
    except Exception as exc:
        return SiteResult(
            slug=slug,
            valid=False,
            status_code=response.status_code,
            reason=f"invalid_json: {exc}",
        )

    if not isinstance(payload, list):
        return SiteResult(
            slug=slug,
            valid=False,
            status_code=response.status_code,
            reason="unexpected_payload: expected list",
        )

    qa_like = sum(1 for posting in payload if isinstance(posting, dict) and _is_qa_like(posting))
    return SiteResult(
        slug=slug,
        valid=True,
        status_code=response.status_code,
        jobs=len(payload),
        qa_like_jobs=qa_like,
    )


def _print_results(results: list[SiteResult]) -> None:
    valid = [item for item in results if item.valid]
    invalid = [item for item in results if not item.valid]

    print(f"Checked: {len(results)}")
    print(f"Valid:   {len(valid)}")
    print(f"Invalid: {len(invalid)}")

    if valid:
        print("\nValid slugs:")
        print("slug\tjobs\tqa_like")
        for item in sorted(valid, key=lambda x: (x.qa_like_jobs, x.jobs), reverse=True):
            print(f"{item.slug}\t{item.jobs}\t{item.qa_like_jobs}")

    if invalid:
        print("\nInvalid slugs:")
        print("slug\treason")
        for item in invalid:
            print(f"{item.slug}\t{item.reason}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate Lever site slugs.")
    parser.add_argument(
        "--sites",
        default="",
        help="Comma-separated Lever site slugs (e.g., company1,company2).",
    )
    parser.add_argument(
        "--file",
        default="",
        help="Optional file path containing slugs (comma-separated or one per line).",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=15,
        help="HTTP timeout in seconds (default: 15).",
    )
    parser.add_argument(
        "--discover-urls",
        default="",
        help="Comma-separated seed URLs to crawl for jobs.lever.co links.",
    )
    parser.add_argument(
        "--discover-file",
        default="",
        help="Optional file with seed URLs (comma-separated or one per line).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    initialize_environment()

    sites: list[str] = []
    if args.sites:
        sites.extend(_split_csv(args.sites))
    if args.file:
        try:
            sites.extend(_load_sites_from_file(Path(args.file)))
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    discover_urls: list[str] = []
    if args.discover_urls:
        discover_urls.extend(_split_csv(args.discover_urls))
    if args.discover_file:
        try:
            discover_urls.extend(_load_sites_from_file(Path(args.discover_file)))
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 2
    if not discover_urls:
        discover_urls = lever_discovery_urls()

    if discover_urls:
        discovered = discover_slugs_from_seed_urls(urls=discover_urls, timeout=args.timeout)
        if discovered:
            print(f"[INFO] Discovered {len(discovered)} slug(s) from seed URLs.")
            sites.extend(discovered)
        else:
            print("[INFO] No Lever slugs discovered from seed URLs.")

    if not sites:
        sites = lever_sites()

    deduped_sites = []
    seen: set[str] = set()
    for site in sites:
        slug = site.strip()
        if not slug or slug in seen:
            continue
        seen.add(slug)
        deduped_sites.append(slug)

    if not deduped_sites:
        print("No Lever site slugs provided.")
        print("Use --sites or set LEVER_SITES in .env.local")
        return 2

    results = [validate_site(slug=slug, timeout=args.timeout) for slug in deduped_sites]
    _print_results(results)
    valid = [item.slug for item in results if item.valid]
    if valid:
        print("\nRecommended LEVER_SITES value:")
        print(",".join(valid))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
