# qa-job-automation

Automated daily QA job monitor that:

- runs at **08:00 IST (02:30 UTC)** using GitHub Actions cron
- fetches jobs across direct sources (RemoteOK + YC + Greenhouse + Lever + Ashby + SmartRecruiters + Workday) and JSearch when `RAPIDAPI_KEY` is set
- applies two filter profiles: `Strict_24h` and `Relaxed_7d` with confidence scoring
- writes diagnostics (`Source_Health`, `Diagnostics`) plus job sheets into `artifacts/jobs.xlsx`
- emails the spreadsheet to the configured recipient

## Sources fetched

- Direct public sources:
  - `RemoteOK`
  - `YC Work at a Startup`
  - `Greenhouse company pages`
  - `Lever company pages`
  - `Ashby company pages` (env-configured org slugs)
  - `SmartRecruiters company pages` (env-configured company slugs)
  - `Workday company pages` (env-configured API URLs)
- JSearch-mapped sources (when a valid `RAPIDAPI_KEY` is set):
  - `LinkedIn`
  - `Naukri`
  - `Indeed`
  - `Glassdoor`
  - `Company career pages`
  - `Wellfound`
  - `Instahyre`
  - `Cutshort`
  - `Hirist`

## Repository layout

- `job_scraper.py` – thin CLI entrypoint that runs the pipeline
- `job_pipeline/constants.py` – static filters, keywords, columns, and source constants
- `job_pipeline/env_config.py` – local env loading and environment config helpers
- `job_pipeline/normalization.py` – parsing and normalization helpers (dates, salary, keyword matching)
- `job_pipeline/http_client.py` – retry/backoff-aware HTTP helpers
- `job_pipeline/sources.py` – source adapters (RemoteOK, YC, JSearch + source mapping)
- `job_pipeline/filtering.py` – core filtering and deduplication logic
- `job_pipeline/pipeline.py` – orchestration (collect, filter, write Excel)
- `scripts/run_pipeline.sh` – shared runner used by both local and GitHub Actions
- `.github/workflows/job-search.yml` – daily scheduler and execution pipeline
- `requirements.txt` – Python dependencies
- `artifacts/` – generated reports (kept out of Git; `.gitkeep` preserves folder)
- `.gitignore` – ignores local caches, virtualenv files, and generated artifacts

## Setup

1. Add GitHub Actions secrets:
   - `RAPIDAPI_KEY` (optional; enables JSearch source for major boards)
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
2. Workflow sends the report to:
   - `harshavardhanvallabhaneni@gmail.com`

## Local environment variables

- Create a local env file from the template:

```bash
cp .env.example .env.local
```

- Edit `.env.local` and set only your real `RAPIDAPI_KEY`.

The scraper auto-loads `.env.local` first, then `.env`.

## Local run

```bash
.venv/bin/python3 -m pip install -r requirements.txt
PYTHON_BIN=.venv/bin/python3 ./scripts/run_pipeline.sh
```

## Notes

- If `RAPIDAPI_KEY` is not set, JSearch-backed sources are skipped and bot-protected boards stay disabled.
- Lever auto-discovery is enabled by default for personal-use convenience.
- If `RAPIDAPI_KEY` is invalid, JSearch-backed sources (including `Naukri`) will not be fetched.
- Excel salary output is normalized to INR (`LPA`) when salary data is present.
- Salary values missing from source data are marked as `Not listed`.
- `Strict_24h` enforces 24-hour recency and salary floor; `Relaxed_7d` uses broader keyword matching and 7-day recency.
- Jobs are ranked by confidence score before deduplication and export.
- GitHub Actions uses the same runner command (`./scripts/run_pipeline.sh`) as local runs.

## Lever slug helper

Validate configured slugs and optionally discover new slugs from seed URLs:

```bash
.venv/bin/python3 scripts/validate_lever_sites.py --discover-urls "https://example.com/careers,https://another.com/jobs"
```
