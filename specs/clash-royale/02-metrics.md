# 02 — Metric Definitions (`cr-price-v1`)

## Unit of observation: the deck appearance

A **deck appearance** is one side of one qualifying battle: one player's 8-card deck plus that battle's result for that player.

- Qualifying battle: Path of Legends ranked, 1v1, involving at least one top-1000 player (see 01).
- Each qualifying battle produces **2 appearances**: the tracked player's deck and the opponent's deck.
- If both players are in the top 1000, the battle appears in both battlelogs but is **stored once** (see Deduplication). It still produces exactly 2 appearances.

## Result per appearance

Compare crowns for each side:

| Condition | Result |
|---|---|
| own crowns > opponent crowns | Win |
| own crowns < opponent crowns | Loss |
| equal | Draw |

## Window

Rolling **7 days** by `battleTime` (UTC): `window_end - 7d ≤ battleTime < window_end`.

Every computation writes a new snapshot row. Old snapshots are never overwritten.

## Formulas

For each card `c` in window `W`:

```
N           = total deck appearances in W              (= 2 × qualifying battles)
n_c         = appearances whose deck contains c
usage%_c    = 100 × n_c / N

wins_c, losses_c, draws_c = results of those n_c appearances
decided_c   = wins_c + losses_c

winrate%_c  = 100 × wins_c / decided_c                  (undefined if decided_c = 0)
adjWR%_c    = 100 × (wins_c + k × 0.5) / (decided_c + k)    with k = 100
price_c     = usage%_c × (adjWR%_c / 50)
```

- **Usage denominator:** all deck appearances in the window, not battles and not players.
- **Win rate denominator:** decided appearances (wins + losses) of decks that contain the card. Draws are excluded and stored separately.
- **adjWR** is like adding `k` imaginary games at 50% (`k/2` wins and `k/2` losses). It keeps small samples from producing extreme prices. As the sample grows, it approaches the raw win rate.
- **Price** equals usage% when adjWR is 50%. It is higher above 50% and lower below it.

## Worked example (must be a unit test)

```
N         = 10,000 appearances (5,000 battles)
n_c       = 2,000            → usage%  = 20.00
wins      = 1,040, losses = 960, draws = 0
winrate%  = 1040 / 2000                  = 52.00
adjWR%    = (1040 + 50) / (2000 + 100)   = 51.905
price     = 20 × (51.905 / 50)           = 20.76
```

Small-sample example: 10 decided games with 9 wins → raw WR 90%, but adjWR = (9 + 50) / (10 + 100) = **53.64%**.

## Edge cases

| Case | Handling |
|---|---|
| Usage across all cards sums to ~800% | Expected, since each deck has 8 cards. Usage means "share of decks containing the card", not a share of the whole. |
| Mirror match (both decks contain `c`) | Counts as 2 appearances: 1 win and 1 loss. Keep this; it correctly pulls the card toward 50%. |
| Card with `n_c = 0` | usage 0, winrate null, adjWR 50, price 0. A snapshot row is still written. |
| `N = 0` (no data in window) | Don't write snapshots. Mark the metrics run as failed with "no data". |
| Low sample (`n_c < 200`) | Store `n_c` and set `is_low_sample = true` so the UI can label it. |
| Evolutions / heroes | v1 aggregates under the base card id. `evolution_level` is stored per deck card for later evo-specific metrics. |
| Tower troops (`supportItems`) | Excluded from v1. |
| Duplicate card in one deck (bad data) | Reject the deck and log it in the run's errors. |
| Mock vs live | Computed separately. Each snapshot has a single `source`. |

## Deduplication

```
battle_key = sha256(battleTime + "|" + min(tagA, tagB) + "|" + max(tagA, tagB))
```

`battle_key` is unique in the database. Re-ingesting the same battlelog, or the same battle from the other player's log, is a no-op.

## Versioning

This spec defines **`cr-price-v1`**: 7-day window, Path of Legends only, both sides, k = 100, draws excluded.

Changing any of these creates a new version (e.g. `cr-price-v2`). Snapshots store `formula_version`, and old versions are never recomputed in place.

## Known biases (document in UI)

- **Opponents may be outside the top 1000.** They are matched by Path of Legends rank, so they are usually close, but not always.
- **Sampling follows top players' activity.** Players who grind more contribute more battles.
- **Polling gaps.** A player who plays more than ~25 battles between polls loses battles. Track `last_polled_at` to monitor this.
