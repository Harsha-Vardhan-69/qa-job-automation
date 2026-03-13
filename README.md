# qa-job-automation

Automated daily QA job monitor that:

- runs at **08:00 IST (02:30 UTC)** using GitHub Actions cron
- fetches jobs across multiple sources (JSearch-backed boards + RemoteOK + YC)
- filters by keywords, location constraints, posting recency, and salary threshold
- deduplicates results and exports `jobs.xlsx`
- emails the spreadsheet to the configured recipient

## Repository layout

- `job_scraper.py` – data collection, filtering, spreadsheet generation, and email delivery
- `.github/workflows/job-search.yml` – daily scheduler and execution pipeline
- `requirements.txt` – Python dependencies

## Setup

1. Add GitHub Actions secrets:
   - `RAPIDAPI_KEY` (optional; enables JSearch source for major boards)
   - `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
2. Workflow sends the report to:
   - `harshavardhanvallabhaneni@gmail.com`

## Local run

```bash
pip install -r requirements.txt
python job_scraper.py --skip-email
```

Optional JSON dump:

```bash
python job_scraper.py --skip-email --dump-json jobs.json
```

## Notes

- If `RAPIDAPI_KEY` is not set, the script still runs using public sources.
- Salary values missing from source data are marked as `Not listed`.
- Jobs older than 24 hours are excluded when posting timestamp is available.
