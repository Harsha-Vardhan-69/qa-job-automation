from __future__ import annotations

import time
from typing import Any

import requests

from .constants import USER_AGENT
from .env_config import http_backoff_seconds, http_max_attempts, http_timeout_seconds

RETRY_STATUS_CODES = {408, 425, 429, 500, 502, 503, 504}


def request_with_retry(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> requests.Response:
    attempts = http_max_attempts()
    backoff = http_backoff_seconds()
    timeout_value = timeout if timeout is not None else http_timeout_seconds()

    merged_headers = {"User-Agent": USER_AGENT}
    if headers:
        merged_headers.update(headers)

    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            response = requests.request(
                method=method.upper(),
                url=url,
                params=params,
                json=json_body,
                headers=merged_headers,
                timeout=timeout_value,
            )
            if response.status_code in RETRY_STATUS_CODES and attempt < attempts:
                sleep_seconds = backoff * (2 ** (attempt - 1))
                time.sleep(sleep_seconds)
                continue
            response.raise_for_status()
            return response
        except requests.RequestException as exc:
            last_exc = exc
            if attempt >= attempts:
                raise
            sleep_seconds = backoff * (2 ** (attempt - 1))
            time.sleep(sleep_seconds)

    if last_exc:
        raise last_exc
    raise RuntimeError(f"Request failed without exception: {method} {url}")


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    response = request_with_retry(
        method="GET",
        url=url,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    return response.json()


def get_text(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> str:
    response = request_with_retry(
        method="GET",
        url=url,
        params=params,
        headers=headers,
        timeout=timeout,
    )
    return response.text


def post_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    json_body: dict[str, Any] | list[Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float | None = None,
) -> Any:
    response = request_with_retry(
        method="POST",
        url=url,
        params=params,
        json_body=json_body,
        headers=headers,
        timeout=timeout,
    )
    return response.json()
