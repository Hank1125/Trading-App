#!/bin/sh
# Print the latest live card prices and recent ingestion runs from Postgres.
cd "$(dirname "$0")/.."
docker compose exec -T -e PGTZ=America/New_York db psql -U metamarket -d metamarket -c "
SELECT c.name, s.usage_pct AS usage, s.win_rate AS wr, s.adj_win_rate AS adj_wr,
       s.price, s.appearances AS n, s.is_low_sample AS low, s.window_end
FROM clashroyale_cardmetricsnapshot s JOIN clashroyale_card c ON c.id = s.card_id
WHERE s.source = 'live' AND s.window_end = (
    SELECT max(window_end) FROM clashroyale_cardmetricsnapshot WHERE source = 'live')
ORDER BY s.price DESC LIMIT ${1:-20};" -c "
SELECT kind, status, started_at::timestamp(0) AS started, finished_at - started_at AS took,
       counts->>'new_battles' AS new_battles, counts->>'errors' AS errors
FROM clashroyale_ingestionrun ORDER BY started_at DESC LIMIT 10;" -c "
SELECT count(*) AS battles, min(battle_time)::timestamp(0) AS oldest, max(battle_time)::timestamp(0) AS newest
FROM clashroyale_battle WHERE source = 'live';"
