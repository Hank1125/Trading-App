#!/bin/sh
# Hourly Clash Royale ingestion + metrics. Schedule with cron, e.g.:
#   5 * * * * /path/to/Trading-App/scripts/cr_hourly.sh
set -e
cd "$(dirname "$0")/.."
mkdir -p logs
.venv/bin/python manage.py cr_hourly >> logs/cr_hourly.log 2>&1
