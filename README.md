# Trading-App — Meta Market

Experimental virtual-points market on the Clash Royale and Rainbow Six Siege meta. **Virtual points only.** Not affiliated with Supercell, Ubisoft or Liquipedia.

This repo holds two backends that are not yet unified:

- **Clash Royale**: Django app at the repo root (`manage.py`, `clashroyale/`, `metamarket/`). Specs in `specs/clash-royale/`.
- **Siege**: FastAPI app in `backend/`.

## Clash Royale data source
Official [Clash Royale API](https://developer.clashroyale.com) (key is tied to whitelisted IPs). Tracks Path of Legends 1v1 battles involving the top 1000 players, rolling 7 days. Price `cr-price-v1` = usage% × (adjusted win rate ÷ 50); see `specs/clash-royale/02-metrics.md`.

## Siege data source
Pro matches from the [Liquipedia](https://liquipedia.net/rainbowsix) MediaWiki API, under the [Liquipedia API terms](https://liquipedia.net/api-terms-of-use). Data is CC-BY-SA 3.0 and must be credited to Liquipedia.

- The client sends a descriptive User-Agent with contact info and makes **at most 1 request every 2 seconds**. Config refuses anything faster.
- Liquipedia records operator **bans**, map veto, and rounds won on attack and defense per map. It does **not** record operator picks, so the Siege price metric is **operator ban rate** in pro play.

## Clash Royale setup

Requires Python 3.11+ and Docker (Postgres 16 on port 5433 via `docker-compose.yml`).

```sh
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env                 # set CLASHROYALE_API_KEY
docker compose up -d db
.venv/bin/python manage.py migrate
.venv/bin/python manage.py cr_hourly  # one live ingest + price snapshot
.venv/bin/python manage.py runserver  # price page at http://127.0.0.1:8000/
scripts/cr_status.sh                  # latest prices and runs in the terminal
```

Hourly updates: `5 * * * * <repo>/scripts/cr_hourly.sh` in crontab (see CLAUDE.md for the macOS permissions it needs).

## Siege backend setup

Requires Python 3.13 and PostgreSQL. Locally, Postgres 16 runs on port 5433.

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env   # then set your email and a random ADMIN_TOKEN
createdb -p 5433 meta_market && createdb -p 5433 meta_market_test

cd backend
../.venv/bin/uvicorn app.main:app --reload     # http://localhost:8000/api/health
```

## Checks (run before every commit)

Clash Royale:

```sh
.venv/bin/python manage.py test clashroyale
.venv/bin/python manage.py makemigrations --check --dry-run
```

Siege:

```sh
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
../.venv/bin/mypy
```

## Known overlaps to resolve

- Both setups use a repo-root `.venv` (Siege needs Python 3.13). Use a separate venv for one of them, e.g. `backend/.venv`.
- Both dev servers default to port 8000, and both expect Postgres on 5433 (Docker for Clash Royale, Homebrew for Siege). Run them on different ports locally.
- Trading and predictions should be shared across both games; the stack for that is not decided yet.
