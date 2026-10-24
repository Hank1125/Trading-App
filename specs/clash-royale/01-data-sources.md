# 01 — Data Sources

Official Clash Royale API: `https://api.clashroyale.com/v1`

## Auth

- Header: `Authorization: Bearer $CLASHROYALE_API_KEY`
- Put the token in `.env`, which is gitignored. Never commit it or send it to the client.
- Keys are tied to **whitelisted IP addresses** (configured at developer.clashroyale.com). Run ingestion from a whitelisted machine. A `403 accessDenied.invalidIp` means the IP is wrong, not the key.
- Player tags contain `#`, which must be URL-encoded as `%23` in paths.

## Endpoints used

### 1. Card catalog: `GET /cards`

Response has `items` (playable cards) and `supportItems` (tower troops).

Fields kept: `id`, `name`, `rarity`, `elixirCost`, `maxLevel`, `maxEvolutionLevel`, `iconUrls.medium`.

- `supportItems` are stored with `is_support = true` and **excluded from v1 metrics**.
- Run at the start of each ingestion so new cards show up automatically.

### 2. Top-1000 players: Path of Legends leaderboard

Candidate endpoints (**to verify against the live API before building on them**):

- `GET /locations/global/pathoflegend/players?limit=…`: current season
- `GET /locations/global/pathoflegend/{seasonId}/rankings/players?limit=…`: a given season

Pages are fetched with `paging.cursors.after`. Keep fetching until we have 1000 players or the list ends.

Fields kept: `tag`, `name`, `rank`.

**Verification task:** confirm the exact path, the maximum `limit`, and the response shape. Save a scrubbed sample response as a test fixture.

### 3. Battles: `GET /players/%23{TAG}/battlelog`

Returns **only the most recent ~25 battles** for that player.

Keep a battle only if:
- `type == "pathOfLegend"`
- `len(team) == 1` and `len(opponent) == 1` (1v1)
- each side has exactly 8 cards in `cards`

Fields kept per battle: `battleTime`, `type`, `gameMode.name`. For each side: `tag`, `crowns`, and for each card `id`, `level`, and `evolutionLevel` (if present).

## Polling

- Each battlelog holds only ~25 battles, so a player who plays more than that between polls loses data. Poll each top-1000 player **every hour**.
- Recompute metrics **every hour**, right after the battle sweep (see 02, Window).
- Refresh the leaderboard **once per day**. A player who drops out of the top 1000 stops being polled, but their battles already stored stay.
- One full battle sweep is about 1000 requests, so hourly polling is about 24,000 requests per day.

## Rate limits and retries

- Limit concurrency to about 5–10 requests at a time.
- Retry `429` and `503` with exponential backoff and jitter (max ~5 attempts).
- A `404` for a player means skip and log. Don't fail the run.
- Every run writes an `IngestionRun` row with counts and errors (see 03).

## Mock mode

Saved JSON fixtures (scrubbed real responses, or synthetic ones) can be loaded with `source = "mock"`. Mock and live rows are never mixed in the same metric snapshot.
