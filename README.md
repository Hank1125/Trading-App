# Trading-App — Meta Market

Experimental virtual-points market on the Clash Royale and Rainbow Six Siege meta. **Virtual points only.** Not affiliated with Supercell, Ubisoft or Liquipedia.

This repo currently holds the **Siege backend** (Python). Clash Royale is being built separately and will be merged in later.

## Siege data source
Pro matches from the [Liquipedia](https://liquipedia.net/rainbowsix) MediaWiki API, under the [Liquipedia API terms](https://liquipedia.net/api-terms-of-use). Data is CC-BY-SA 3.0 and must be credited to Liquipedia.

- The client sends a descriptive User-Agent with contact info and makes **at most 1 request every 2 seconds**. Config refuses anything faster.
- Liquipedia records operator **bans**, map veto, and rounds won on attack and defense per map. It does **not** record operator picks, so the Siege price metric is **operator ban rate** in pro play.

## Backend setup

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

```sh
cd backend
../.venv/bin/python -m pytest -q
../.venv/bin/ruff check . && ../.venv/bin/ruff format --check .
../.venv/bin/mypy
```
