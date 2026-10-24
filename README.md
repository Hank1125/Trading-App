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

Requires Python 3.13 and PostgreSQL 16. Both games share one database: the Docker Postgres from `docker-compose.yml` (`metamarket`/`metamarket` on localhost:5433), or an identical local Postgres with the same role and database.

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements-dev.txt
cp backend/.env.example backend/.env   # then set your email and a random ADMIN_TOKEN
# Without Docker, create the same role/databases in a local Postgres on 5433:
#   CREATE ROLE metamarket LOGIN PASSWORD 'metamarket' CREATEDB;
#   CREATE DATABASE metamarket OWNER metamarket;
#   CREATE DATABASE metamarket_siege_test OWNER metamarket;   -- disposable, wiped by tests

cd backend
../.venv/bin/alembic upgrade head                        # create tables
../.venv/bin/python -m scripts.seed_catalog              # 78 operators + 28 maps (safe to re-run)
../.venv/bin/python -m scripts.ingest_fixture blast-2026-may   # load the May 2026 Major (safe to re-run)
../.venv/bin/uvicorn app.main:app --reload               # http://localhost:8000/api/health
```

### Name matching
Liquipedia match pages spell names inconsistently, so every name goes through `name_key` before matching: accents, case and punctuation are ignored (`Capitao` = `Capitão`, `FURIA` = `Furia`). On top of that there are two short, explicit alias tables in `app/siege/catalog.py`: `Valk` → Valkyrie, and `Ninjas In Pyjamas` → NIP. A match containing a name that still doesn't resolve is **quarantined whole** (`siege_quarantine`) and never counted. Liquipedia edits to a map that was already finished are applied, and the before/after is logged in `siege_correction`.

## Replay demo data
`DATA_MODE=replay` replays the real **BLAST Major Salt Lake City 2026 (May)** on an accelerated demo clock. The wikitext is saved, unmodified, in `backend/fixtures/siege/blast-2026-may/`, together with revision IDs and checksums. Content © Liquipedia contributors, CC-BY-SA 3.0. To refresh it, run this from `backend/`:

```sh
../.venv/bin/python -m scripts.fetch_fixture blast-2026-may "BLAST Major/2026/May" "BLAST Major/2026/May/Phase 2"
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

## How the two halves fit together

- **One venv:** a repo-root `.venv` on Python 3.13 holds both `requirements.txt` (Django/Clash) and `backend/requirements-dev.txt` (Siege). Both suites pass in it.
- **One database:** both use the `metamarket` Postgres on localhost:5433 (Docker per `docker-compose.yml`, or a local Postgres with the same role/db). Clash tables are `clashroyale_*` (Django migrations) and Siege tables are `siege_*` (Alembic, `backend/migrations`).
- **Trading and predictions** are shared across both games and live in the Django `markets` app.
- **Dev servers:** Django on 8000. Run the Siege FastAPI health server on another port if needed (`uvicorn app.main:app --port 8100`).

## Demo runbook (Kalshi-style UP/DOWN markets, virtual points)

One-time setup, from the repo root:
```sh
.venv/bin/python manage.py migrate                                    # Django: clashroyale + markets tables
(cd backend && ../.venv/bin/alembic upgrade head \
   && ../.venv/bin/python -m scripts.seed_catalog \
   && ../.venv/bin/python -m scripts.ingest_replay_history blast-2026-may)   # Siege: real May Major, map by map
```

**Clash Royale (live):** put `CLASHROYALE_API_KEY=...` in `.env`. The key must allow this machine's public IP. Then:
```sh
.venv/bin/python manage.py cr_hourly            # ingest top-player battles + write this hour's prices (~1-2 min)
# keep prices moving: run it again every hour (cron: 5 * * * * <repo>/scripts/cr_hourly.sh)
```

Run the demo in three terminals:
```sh
.venv/bin/python manage.py markets_demo_clock --game siege --start 2026-05-10T15:00:00+00:00 --speed 60
.venv/bin/python manage.py markets_worker       # terminal 1: opens / closes / settles windows
.venv/bin/python manage.py runserver            # terminal 2: http://127.0.0.1:8000/markets/
```

**What to show (3 min):**
1. `/markets/?game=siege`: the **REPLAY** badge (real May 2026 Major results at 60×, so one hourly window ≈ one real minute). Each tile shows the stat at window start vs now, UP and DOWN prices, a countdown, and **how many people are on each side**.
2. Open **Mira ban rate**. Buy 10 UP, see the exact quote, confirm, and watch the UP price move. Retrying the same confirm doesn't charge twice.
3. When a map lands during the window, the stat moves. At close the market settles: UP if it rose, DOWN if it fell, VOID with a refund if unchanged. The evidence is on the market page.
4. `/markets/?game=clash_royale`: **LIVE** card-price markets. Each one opens once the hour's price snapshot is written (~:05) and settles on the next hour's snapshot.
5. `/markets/portfolio/`: balance, positions, and the full ledger (grant, trades, payouts and refunds).

Stop the replay with `markets_demo_clock --game siege --stop`. Known limits: pro Siege stats only move when maps finish, so many hourly windows void. Clash markets move hourly in real time.
