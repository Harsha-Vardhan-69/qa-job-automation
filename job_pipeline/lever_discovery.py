from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any
from urllib.parse import urlparse

from .constants import REQUEST_TIMEOUT_SECONDS
from .env_config import compact
from .http_client import get_text

_LEVER_LINK_REGEX = re.compile(
    r"https?://jobs\.lever\.co/([a-zA-Z0-9][a-zA-Z0-9._-]*)",
    flags=re.IGNORECASE,
)


def _dedupe(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in items:
        item = compact(raw).strip("/").lower()
        if not item or item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def extract_slug_from_url(value: str) -> str | None:
    raw = compact(value)
    if not raw:
        return None

    parsed = urlparse(raw)
    if parsed.netloc.lower() != "jobs.lever.co":
        return None

    path_parts = [part for part in parsed.path.split("/") if part]
    if not path_parts:
        return None

    slug = compact(path_parts[0]).lower()
    if not re.match(r"^[a-z0-9][a-z0-9._-]*$", slug):
        return None
    return slug


def extract_slugs_from_text(value: str) -> list[str]:
    if not value:
        return []
    matches = [match.group(1).lower() for match in _LEVER_LINK_REGEX.finditer(value)]
    return _dedupe(matches)


def discover_slugs_from_jobs(jobs: list[dict[str, Any]]) -> list[str]:
    candidates: list[str] = []
    for job in jobs:
        for key in ("Direct Apply Link", "Company", "Required Skills"):
            value = str(job.get(key) or "")
            slug = extract_slug_from_url(value)
            if slug:
                candidates.append(slug)
            candidates.extend(extract_slugs_from_text(value))
    return _dedupe(candidates)


def discover_slugs_from_seed_urls(urls: list[str], timeout: int = REQUEST_TIMEOUT_SECONDS) -> list[str]:
    slugs: list[str] = []
    for seed in _dedupe(urls):
        slug_from_url = extract_slug_from_url(seed)
        if slug_from_url:
            slugs.append(slug_from_url)

        try:
            page_text = get_text(seed, timeout=timeout)
        except Exception as exc:
            print(f"[WARN] Lever discovery seed fetch failed for '{seed}': {exc}")
            continue

        slugs.extend(extract_slugs_from_text(page_text))

    return _dedupe(slugs)


def discover_lever_slugs(jobs: list[dict[str, Any]], seed_urls: list[str]) -> list[str]:
    job_slugs = discover_slugs_from_jobs(jobs)
    seed_slugs = discover_slugs_from_seed_urls(urls=seed_urls)
    return _dedupe([*job_slugs, *seed_slugs])
