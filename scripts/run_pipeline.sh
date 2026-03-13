#!/usr/bin/env bash
set -euo pipefail

PYTHON_BIN="${PYTHON_BIN:-python3}"
OUTPUT_PATH="${OUTPUT_PATH:-artifacts/jobs.xlsx}"
cmd=("$PYTHON_BIN" "job_scraper.py" "--output" "$OUTPUT_PATH")

echo "[INFO] Running pipeline command: ${cmd[*]}"
"${cmd[@]}"
