import os
from pathlib import Path

from .constants import (
    DEFAULT_ASHBY_ORGS,
    DEFAULT_GREENHOUSE_BOARDS,
    DEFAULT_SMARTRECRUITERS_COMPANIES,
    DEFAULT_WORKDAY_API_URLS,
    HTTP_BACKOFF_SECONDS,
    HTTP_MAX_ATTEMPTS,
    REQUEST_TIMEOUT_SECONDS,
)


_ENV_LOADED = False


def compact(value: object) -> str:
    return " ".join(str(value or "").split())


def load_local_env_files(base_dir: str | None = None) -> None:
    """Load .env.local and .env without overriding existing env vars."""
    base_path = Path(base_dir or Path(__file__).resolve().parents[1])

    for filename in (".env.local", ".env"):
        env_path = base_path / filename
        if not env_path.exists():
            continue

        try:
            for raw_line in env_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export ") :].strip()
                if "=" not in line:
                    continue

                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError as exc:
            print(f"[WARN] Could not read {env_path}: {exc}")


def initialize_environment(base_dir: str | None = None) -> None:
    global _ENV_LOADED
    if _ENV_LOADED:
        return
    load_local_env_files(base_dir=base_dir)
    _ENV_LOADED = True


def env_value(name: str, default: str = "") -> str:
    return compact(os.getenv(name, default)).strip('"').strip("'")


def _csv_values(name: str, default_values: list[str] | None = None) -> list[str]:
    raw = env_value(name, "")
    if raw:
        values = [compact(part) for part in raw.split(",")]
        return [value for value in values if value]
    return list(default_values or [])


def bool_env(name: str, default: bool = False) -> bool:
    raw = env_value(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "y", "on"}


def greenhouse_boards() -> list[str]:
    return _csv_values("GREENHOUSE_BOARDS", DEFAULT_GREENHOUSE_BOARDS)


def ashby_orgs() -> list[str]:
    return _csv_values("ASHBY_ORGS", DEFAULT_ASHBY_ORGS)


def smartrecruiters_companies() -> list[str]:
    return _csv_values("SMARTRECRUITERS_COMPANIES", DEFAULT_SMARTRECRUITERS_COMPANIES)


def workday_api_urls() -> list[str]:
    return _csv_values("WORKDAY_API_URLS", DEFAULT_WORKDAY_API_URLS)


def smartrecruiters_max_pages() -> int:
    raw = env_value("SMARTRECRUITERS_MAX_PAGES", "3")
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return 3


def workday_max_pages() -> int:
    raw = env_value("WORKDAY_MAX_PAGES", "3")
    try:
        return max(1, min(20, int(raw)))
    except ValueError:
        return 3


def lever_sites() -> list[str]:
    return _csv_values("LEVER_SITES", [])


def enable_lever_autodiscovery() -> bool:
    # Default enabled for personal-project convenience.
    return bool_env("ENABLE_LEVER_AUTODISCOVERY", default=True)


def lever_discovery_urls() -> list[str]:
    return _csv_values("LEVER_DISCOVERY_URLS", [])


def usd_to_inr() -> float:
    value = env_value("USD_TO_INR", "83.0")
    try:
        return float(value)
    except ValueError:
        return 83.0


def http_timeout_seconds() -> float:
    raw = env_value("HTTP_TIMEOUT_SECONDS", str(REQUEST_TIMEOUT_SECONDS))
    try:
        return max(1.0, float(raw))
    except ValueError:
        return float(REQUEST_TIMEOUT_SECONDS)


def http_max_attempts() -> int:
    raw = env_value("HTTP_MAX_ATTEMPTS", str(HTTP_MAX_ATTEMPTS))
    try:
        return max(1, min(8, int(raw)))
    except ValueError:
        return HTTP_MAX_ATTEMPTS


def http_backoff_seconds() -> float:
    raw = env_value("HTTP_BACKOFF_SECONDS", str(HTTP_BACKOFF_SECONDS))
    try:
        return max(0.1, float(raw))
    except ValueError:
        return HTTP_BACKOFF_SECONDS


def jsearch_request_config() -> dict[str, str]:
    return {
        "country": env_value("JSEARCH_COUNTRY", "in"),
        "date_posted": env_value("JSEARCH_DATE_POSTED", "all"),
        "page": env_value("JSEARCH_PAGE", "1"),
        "num_pages": env_value("JSEARCH_NUM_PAGES", "1"),
    }
