# Clash Royale — Data & Metrics Specs

Branch: `CLashRoyale`. This branch covers only Clash Royale data. Siege, trading, and predictions are out of scope here.

## Phase goal

1. Pull real data from the official Clash Royale API (key required; see [01-data-sources.md](01-data-sources.md)).
2. Calculate per-card **usage rate** and **win rate** over a rolling window.
3. Derive a reference **price** for each card:

   ```
   price = usage% × (adjusted_winrate% / 50%)
   ```

4. Store the card catalog, raw battles, and timestamped metric snapshots in Postgres.

## Decisions (agreed)

| Topic | Decision |
|---|---|
| Population | **Both sides** of every battle played by a top-1000 Path of Legends player |
| Game modes | **Path of Legends ranked 1v1 only** |
| Window | Rolling 7 days by `battleTime` (UTC) |
| Win rate | Wins / (wins + losses); draws excluded and reported separately |
| Adjusted win rate | Bayesian shrinkage toward 50%, k = 100 |
| Formula version | `cr-price-v1` |
| Stack | Django + Postgres |
| "Meta rate" | Means **win rate**; there is no separate metric |

## Specs

- [01-data-sources.md](01-data-sources.md): API endpoints, auth, polling, rate limits
- [02-metrics.md](02-metrics.md): exact metric definitions, worked example, edge cases
- [03-database.md](03-database.md): Django models and constraints

## Done when

- Running ingestion twice never double-counts a battle.
- The metric math has unit tests, including the worked example in 02.
- Every snapshot records its source (`live`/`mock`), window, sample size, formula version, and compute time.
