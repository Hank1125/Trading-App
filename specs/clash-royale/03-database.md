# 03 — Database (Django app `clashroyale`, Postgres)

All timestamps are UTC (`USE_TZ = True`). `source` is always `"live"` or `"mock"`.

## Models

### Card
| Field | Type | Notes |
|---|---|---|
| api_id | int, **unique** | `id` from `/cards` |
| name | str | |
| rarity | str | common / rare / epic / legendary / champion |
| elixir | int, null | some cards have no `elixirCost` |
| max_level | int | |
| max_evolution_level | int, default 0 | |
| icon_url | url | |
| is_support | bool | true for tower troops (excluded from v1 metrics) |
| updated_at | datetime | auto |

### Player
| Field | Type | Notes |
|---|---|---|
| tag | str, **unique** | stored with leading `#` |
| name | str | |
| last_rank | int, null | rank from the most recent leaderboard sync |
| last_seen_in_top | datetime, null | |
| last_polled_at | datetime, null | last battlelog fetch |

### IngestionRun
| Field | Type | Notes |
|---|---|---|
| kind | choice | `cards` / `leaderboard` / `battles` / `metrics` |
| source | choice | `live` / `mock` |
| started_at, finished_at | datetime | |
| status | choice | `running` / `ok` / `partial` / `failed` |
| counts | JSON | e.g. `{"fetched": 1000, "new_battles": 4210, "skipped": 12}` |
| error | text | |

### Battle
| Field | Type | Notes |
|---|---|---|
| battle_key | char(64), **unique** | sha256 dedup key (see 02) |
| battle_time | datetime, **indexed** | |
| type | str | `pathOfLegend` |
| game_mode | str | |
| source | choice | |
| ingestion_run | FK → IngestionRun | the run that first inserted it |

### BattleDeck
| Field | Type | Notes |
|---|---|---|
| battle | FK → Battle | |
| side | smallint (0/1) | **unique together with battle**. 0 = lower tag, 1 = higher tag, so it doesn't depend on whose log we read |
| player_tag | str | |
| is_tracked_top1000 | bool | was this player in the top 1000 when ingested |
| crowns | smallint | |
| result | choice | `W` / `L` / `D` |

### BattleDeckCard
| Field | Type | Notes |
|---|---|---|
| deck | FK → BattleDeck | |
| card | FK → Card | |
| level | smallint | |
| evolution_level | smallint, default 0 | |

Constraint: **unique (deck, card)**. Each deck has exactly 8 rows, checked on ingest.

### CardMetricSnapshot
| Field | Type | Notes |
|---|---|---|
| card | FK → Card | |
| source | choice | |
| formula_version | str | `cr-price-v1` |
| window_start, window_end | datetime | |
| computed_at | datetime | |
| total_appearances | int | N |
| appearances | int | n_c |
| wins, losses, draws | int | |
| usage_pct | decimal(7,4) | |
| win_rate | decimal(7,4), null | null when no decided games |
| adj_win_rate | decimal(7,4) | |
| price | decimal(10,4) | |
| is_low_sample | bool | n_c < 200 |

Constraint: **unique (card, window_end, formula_version, source)**.
Index: (card, formula_version, source, window_end) for history charts.

## Ingestion rules

- Insert each battle together with its 2 decks and 16 deck cards in **one transaction**. On a `battle_key` conflict, skip the whole battle.
- Unknown card id in a battle: sync `/cards` again once. If it's still unknown, skip the battle and log it.
- Raw battles are append-only. Metrics are always recomputed from raw rows, never edited incrementally.

## Management commands

| Command | Does |
|---|---|
| `cr_sync_cards` | Upsert the card catalog |
| `cr_sync_top_players` | Refresh the top-1000 Player rows |
| `cr_ingest_battles` | Poll battlelogs for tracked players and insert new battles |
| `cr_compute_metrics [--window-end] [--source]` | Write a CardMetricSnapshot for every non-support card |
| `cr_load_mock` | Load fixture JSON with `source=mock` |

The metric math lives in `clashroyale/metrics.py` as pure functions over plain deck/result lists, with no ORM access, so it can be unit-tested directly.
