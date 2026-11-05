#!/usr/bin/env bash
# Pulls any newly posted council minutes and regenerates web/public/data.json.
# Safe to re-run: PDFs already in pdfs/ are skipped, and council.db is rebuilt
# from parsed/ each time so a meeting whose agenda was later replaced by
# minutes never leaves stale rows behind. Used by the scheduled GitHub Action
# (.github/workflows/update-data.yml), and can be run locally the same way.
set -euo pipefail
cd "$(dirname "$0")"

python3 1_download_minutes.py
python3 2_parse_minutes.py
rm -f dbs/council.db
python3 create_database.py
python3 import_json.py
python3 export_dashboard_data.py
