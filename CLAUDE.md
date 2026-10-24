# Clash Royale & Rainbow Six Siege Stocks and Meta Markets

## Working rules (from the project owner, take precedence)

1. **Explain every small change.** For each edit, state what changed and why, in plain language, before moving on. Keep changes small enough that each one can be explained in a sentence or two.
2. **Test before committing.** Run the relevant tests (and typecheck/build once they exist) before every commit. Do not commit if they fail; report the actual output instead. If there is nothing testable yet, say so explicitly in the commit summary.

## Mission and scope

Build a runnable, convincing MVP in **five hours**. Users switch between Clash Royale cards and Rainbow Six Siege operators, explore performance, trade virtual shares, and stake virtual points on future usage/pick-rate or win-rate metrics. Results derive from versioned game-data snapshots. Deliver working vertical slices before polish.

The supplied project spec defines leaderboard ingestion, ranked 1v1 filtering, deduplication, usage, Bayesian-adjusted win rate, and price. The implementation choices below fill gaps in that spec; they are deliberate MVP defaults, not additional user requirements.

**Virtual points only.** Points cannot be purchased, withdrawn, transferred between users, redeemed, or converted to money. Do not integrate PYUSD, wallets, blockchain, deposits, cash prizes, real-money betting, or payment credentials without explicit user authorization and a separately scoped review. Authorization to build this MVP does not authorize those features.

Do not claim the outcome is impossible to predict, manipulate, or know in advance. Describe it as an experimental simulation using a sampled, potentially incomplete game-data feed. Do not imply Supercell or Ubisoft endorsement.

## Claude Code working contract

1. Read repository instructions and inspect existing code, scripts, dependencies, and Git status first. Preserve unrelated work. Adapt this plan to an existing working stack rather than rewriting it.
2. Within 10 minutes, produce a short task checklist, identify the critical path, and start a runnable vertical slice. Record material assumptions in README. Continue autonomously on reversible implementation decisions.
3. Keep the five-hour clock visible. At each checkpoint, report what works, what is blocked, tests run, and the next cut. If an integration blocks progress for 15 minutes, ship the mock path and record the blocker.
4. Implement real routes, persistence, validation, and error states. Do not substitute hardcoded successful responses for trading, staking, settlement, or ledger writes. Seeded data must be labeled.
5. Keep calculation and settlement functions pure and independently testable. Keep API secrets, accounting, quotes, clocks, and settlement authority server-side.
6. Use database transactions, uniqueness constraints, and idempotency for financial-like state changes. Never rely only on a disabled button, an in-memory flag, or a prior balance read.
7. Never silently switch a live market to mock data. Never change the rules of a market after creation. Never edit a published snapshot or settled payout in place.
8. Use integer point units and explicit rounding. Reject malformed, negative, non-finite, overflowing, or out-of-range inputs. Never trust client balances, prices, timestamps, outcomes, or user IDs.
9. Do not expose secrets in logs, client bundles, screenshots, fixtures, or commits. Do not run destructive database resets outside an explicitly selected disposable demo database.
10. Run meaningful tests and the production build. Report actual results; do not claim tests, API access, or deployment succeeded without evidence. Document remaining gaps.
11. No new infrastructure, optional integrations, speculative abstractions, or unrelated refactors before the acceptance checklist passes. Do not deploy publicly without authorization.
12. Finish with startup instructions, environment variables, test results, known limitations, and a three-minute demo script. If time runs out, deliver the last runnable slice and clearly identify incomplete requirements.

## MVP stack and topology

If starting from scratch, use TypeScript, Next.js App Router, simple Tailwind styling, Prisma with SQLite, Zod validation, and Vitest. Use the repository's package manager; default to npm. Pin installed versions with a lockfile. Use a small chart library only if already available or quick to integrate.

Run one web process and one explicit Node worker sharing a local persistent database on one host. Worker commands perform ingest, snapshot publication, and due-market settlement. Do not rely on browser visits, request timers, or serverless background execution for jobs. No Redis, Kafka, microservices, WebSockets, order book, or blockchain.

SQLite is the scoped deployment choice, not a claim of horizontal scalability. Document a future PostgreSQL/auth/worker-hardening migration without implementing it. Use short serialized write transactions with bounded busy retries; do network requests before opening transactions.

Suggested layout: `app/`, `components/`, `lib/domain/`, `lib/db/`, `lib/providers/`, `scripts/`, `fixtures/`, `tests/`. Keep modules small; avoid architecture work that delays the first usable screen.

## Shared two-game scope

Ship both game views in the five-hour MVP using one trading, ledger, snapshot, pool, and settlement engine. Keep ingestion and metric calculations game-specific. Clash Royale live ingestion is optional if credentials work; **Siege defaults to deterministic mock round data** until a suitable authorized provider is verified. Do not spend the hackathon reverse-engineering a Siege API.

Use `gameId = clash_royale | rainbow_six_siege` and a shared `Asset` with `(gameId, externalId)`, kind `card | operator`, display name, and optional side. Replace card-specific database references below with `assetId`; retain card terminology only inside the Clash adapter. Use `AssetMetric` instead of `CardMetric`. Store `gameId` on snapshots and markets, and validate it against assets, quotes, positions, evidence, and settlement rules. Use `(userId, namespace, gameId, assetId)` position uniqueness. Add `RoundObservation`, `Round`, and `SnapshotRound` for Siege instead of forcing rounds into the Clash battle schema.

One demo account and ledger can serve both games in the same data-mode database. Its starting grant happens once, not once per game. Use a game selector and shared asset/detail components. Keep charts, rankings, and metric comparisons within one game and one cohort. Never treat card usage and operator pick rate as the same population statistic.

For the five-hour build, `DATA_MODE=mock` drives both games. In a separately configured live database, enable only games with verified live providers; unavailable games show an explicit unavailable state. Do not blend mock Siege assets into a live wallet. Demonstrate both games in mock mode and any live adapter separately.

## Environment and runnable commands

Commit `.env.example`, never `.env`. Document and wire these variables:

```dotenv
DATABASE_URL="file:./dev.db"
DATA_MODE="mock"
CLASH_API_BASE_URL="https://api.clashroyale.com/v1"
CLASH_API_TOKEN=""
PLAYER_LIMIT="100"
POLL_INTERVAL_SECONDS="300"
SNAPSHOT_INTERVAL_SECONDS="300"
METRIC_WINDOW_SECONDS="86400"
MIN_SNAPSHOT_BATTLES="50"
MIN_SNAPSHOT_ROUNDS="50"
SIEGE_DATA_SOURCE="mock"
MAX_QUOTE_AGE_SECONDS="900"
SETTLEMENT_GRACE_SECONDS="600"
DEMO_MODE="true"
SESSION_SECRET="replace-with-a-long-random-local-secret"
ADMIN_TOKEN="replace-with-a-separate-random-local-secret"
```

Validate configuration on startup. Siege supports `mock` initially; reject unsupported source values until an authorized live adapter is implemented. Clash live mode requires a token; missing credentials must produce a useful error, not an implicit mode switch. Resolve database paths consistently across web and worker. Keep tokens server-only, including the optional admin token.

Provide these scripts, adapting names consistently if the repository already has equivalents:

```sh
npm install
cp .env.example .env
npm run db:migrate
npm run seed
npm run dev                 # terminal 1
npm run worker              # terminal 2
npm run ingest:once
npm run snapshot:once
npm run settle:due
npm test
npm run typecheck
npm run build
npm run demo:reset          # mock/demo DB only; guard against live mode
```

Seeding is idempotent. Restarting the app must preserve balances, positions, stakes, and settlements. Include a health/status view for source mode, last successful poll, error count, accepted battles, last snapshot, and worker heartbeat.

## Clash Royale data ingestion

### Provider and live verification

Use the official API as the intended live source: https://developer.clashroyale.com/#/documentation. Its dynamic docs were not independently readable when this file was authored. **Verify current leaderboard endpoint, pagination, authentication, response schema, battle-log depth, and ranked-mode identifiers against official docs and a real response before claiming live support.** Do not guess an endpoint or copy a third-party schema and call it verified.

Create a narrow provider interface for `listRankedPlayers`, `getBattleLog`, and `getCards`; implement mock and live adapters. Record verified endpoint paths and example sanitized payloads in README/fixtures. Encode player tags as path components. Set request timeouts and validate responses.

The supplied spec targets approximately 1,000 top ranked players. Start with 100, configurable up to 1,000. Record the sampled cohort and ranking retrieval time; both decks in a qualifying sampled battle count even if the opponent is outside the cohort. Describe metrics as sampled top-player battle activity, not all-player population statistics.

The supplied spec notes IP-restricted keys and recent logs of about 25 battles. Confirm these assumptions. Use configured fixed egress for live access; if unavailable, continue in explicit mock mode. A proxy is optional only if explicitly configured and trusted; never forward the API token to an arbitrary host.

Begin collection immediately at project start. The original suggestion of 10:30 is not a scheduler requirement. Poll every five minutes initially, with bounded concurrency (start at 3), configurable limits, and no claim of complete history. A 2–3-hour poll can miss games when recent logs overflow. Back off on 429 and transient errors, honor Retry-After, add jitter, and cap retries. Stop retrying authentication failures; show the configuration issue. Record incomplete polls and possible gaps.

### Filtering and normalization

- Accept only verified ranked 1v1 modes from an explicit allowlist. Reject 2v2, friendly, challenges, events, malformed entries, and unknown modes. Do not infer ranked mode solely from trophies or deck length.
- Require one player per side, two different normalized player tags, eight distinct base card IDs per deck, a valid UTC battle time, and supported outcome fields.
- Merge evolved and ordinary versions by canonical base card ID. Preserve original evolution metadata in raw evidence. Unknown cards are quarantined until mapped, not silently omitted.
- Decide outcomes from verified result fields. For the MVP, exclude draws and ambiguous outcomes from both usage and win calculations; count them as exclusions. Do not guess a winner from a tied crown count.
- Reject implausible future timestamps. Keep raw provider payload, fetched-at time, normalization version, and rejection reason where applicable.

### Canonical identity and deduplication

Normalize tags consistently, sort both tags lexicographically, and hash `sourceNamespace | battleTimeUTC | sortedTagA | sortedTagB` as the canonical battle key. Align decks and winner with the sorted players, not with the caller's team/opponent order. Enforce a database unique constraint on the key.

Store observation metadata separately so repeat sightings do not increase the battle count. If the same key yields conflicting canonical decks/outcomes, quarantine the conflict and flag it; never overwrite accepted evidence silently. Preserve first observation time, which matters for settlement eligibility. Repeated polls and reversed perspectives must yield exactly one normalized battle.

## Clash Royale metrics and shared snapshot/price rules

Use equal weights for the MVP. Defer trophies, Elo, and PageRank weighting: they change metric semantics and require separate validation and a new formula version.

For a snapshot ending at UTC time `T`, include eligible battles with `T - window <= battleTime < T`. Default window is 24 hours. Initial live coverage may be much shorter; show available coverage, counts, and gaps rather than pretending to have a full day of history.

Let `B` be the number of accepted decisive battles and `D = 2B` the number of decks:

```text
cardDecks = number of those decks containing the card
usageFraction = cardDecks / D
usagePct = 100 * usageFraction

nonMirrorGames = battles where exactly one deck contains the card
nonMirrorWins = those battles won by the deck containing the card
rawWinFraction = nonMirrorWins / nonMirrorGames   # null if zero
adjustedWinFraction = (nonMirrorWins + 25) / (nonMirrorGames + 50)

pricePoints = usagePct * (adjustedWinFraction / 0.50)
```

Mirror matches count two card appearances toward usage but contribute nothing to that card's win-rate denominator. With no non-mirror games, adjusted win rate is 50%; label it prior-only. With no eligible battles, usage and price are unavailable, not zero.

Use **percentage points** for `usagePct`: 20% usage and 55% adjusted win rate produces **22.00 points per share**, not 0.22. Formula version: `usage-adjusted-win-v1`. Keep this formula unweighted.

Store money-like values in hundredths of a virtual point: 1 point = 100 integer units. Compute the quote using integer/rational arithmetic and round half-up once to units. Do not impose an unexplained price floor. A zero-price card is viewable but not tradable; never give away shares for free. Reject new trades if the snapshot has fewer than the configured minimum battles or is too old. Display these reasons.

Publish all card metrics for a snapshot in one transaction. Store snapshot ID, namespace, window bounds, ingestion cutoff, publication time, cohort ID, coverage/error metadata, battle count, formula/filter versions, evidence hash, and constituent battle IDs. Store per-card counts, exact numerator/denominator values, display metrics, and integer quote. Unique constraints prevent duplicate snapshot publication for the same run identity. Readers see only complete published snapshots.

Snapshots are immutable. Price charts use successive snapshots from the same source and formula version. Trading volume does not change the reference price. This is an app-issued, unlimited-inventory simulation of a data index; it is not price discovery or a realistic exchange.

## Rainbow Six Siege ingestion, metrics, and settlement

### Data contract and source boundary

Implement a `SiegeProvider` with catalog and round-log methods returning a validated internal schema. No live Siege endpoint or access entitlement is assumed. Verify provider authorization, documented schema, rate limits, coverage, timestamps, and round-level outcomes before adding a live adapter. Never fabricate an official API, scrape authenticated sessions, request users' Ubisoft passwords, or label synthetic numbers as live.

Use authorized round-level records if available. Aggregate operator percentages alone cannot establish individual round membership, deduplication, cutoff eligibility, or a reproducible rolling window; do not use them to settle this MVP's markets. Published balance charts can provide context but are not the live feed.

Ubisoft distinguishes presence (selection when not banned) from Win Delta, which is aggregated per bomb site. **Win Delta is not raw win rate, and presence is not this app's unconditional pick rate.** Do not convert Win Delta into win percentage by adding 50. Source: [Ubisoft Designer's Notes](https://www.ubisoft.com/en-gb/game/rainbow-six/siege/news-updates/77Iv7UsgPeQzJzbBQSTZaB/y9s33-designers-notes). The following are explicit app-defined metrics, not an attempt to reproduce Ubisoft's balance methodology.

Each accepted record must include provider/match ID, stable round ID or index, round completion time, first observation time, ranked playlist, platform, rank cohort, patch, map/site if provided, attacking/defending team identity, final operator selections at action-phase start, and winning side. Retain raw evidence and normalization version. Use the team **side in that round**, since teams can switch sides.

For the MVP accept only complete decisive ranked rounds with five distinct valid attackers and five distinct valid defenders. Reject missing selections, unknown operators, inconsistent sides, incomplete/abandoned rounds, unknown mode, and ambiguous outcomes. Count exclusions. This defines the sample and can bias it; show coverage limitations. Attribute an operator appearance once per completed round even if that player dies; use the round outcome, not match victory, player kills, or survival. Use final selections after any selection changes, not every operator hovered or initially chosen.

Deduplicate using `namespace | provider | matchId | roundId` with a database unique constraint, regardless of which player supplied the record. Never deduplicate by timestamp alone. Quarantine conflicting records under the same key, preserve earliest observation, and reuse the shared retry/poll audit pattern. Keep all ten appearances in one atomic accepted round.

### Pick rate, round win rate, and operator price

Freeze one ranked platform/rank/patch cohort per Siege snapshot and market. For the hackathon use one fixture cohort and one patch, with both sides represented; do not build arbitrary cohort filtering. Keep different patches and platforms separate. Show map/site composition as context where available; defer map-adjusted skill/balance analysis.

For each operator on its catalog side within the frozen time window:

```text
R = accepted rounds in the cohort with a complete lineup for that side
P = those rounds where the operator was selected
W = those selected rounds won by the operator's side

pickRatePct = 100 * P / R                 # null if R == 0
rawRoundWinPct = 100 * W / P              # null if P == 0
adjustedRoundWinFraction = (W + 25) / (P + 50)
adjustedRoundWinPct = 100 * adjustedRoundWinFraction
operatorPricePoints = pickRatePct * (adjustedRoundWinFraction / 0.50)
```

A pick is one team-round appearance, not one fifth of a lineup slot. An operator selected in 20 of 100 rounds has a 20% pick rate. Across a complete five-operator side, pick rates sum to 500%, not 100%. Banned or otherwise unavailable operators contribute zero picks while rounds remain in the unconditional denominator; label the metric accordingly. Operators must belong to the frozen patch catalog. Optional ban-aware presence is deferred and must not silently replace this denominator.

Use formula version `siege-pick-adjusted-round-win-v1`. Keep the 50% prior as a transparent MVP convention; attack/defense and map effects mean this price is descriptive, not a causal strength estimate. No Clash mirror-match exclusion applies to Siege. Apply the shared integer quote rounding, zero-price rejection, stale-quote checks, and immutable publication rules. Persist `R`, `P`, `W`, exact fractions, side, cohort, patch, and constituent round IDs.

For example, `R=100, P=20, W=12` gives 20% pick rate, 60% raw round win rate, `(12+25)/(20+50)=52.8571...%` adjusted win rate, and a **21.14-point** price after rounding. No picks means a prior-only 50% adjusted rate and a zero, nontradable quote; no rounds means unavailable metrics.

### Siege prediction rules

Example: “Will Ash's pick rate be at least 25% in the sampled ranked attacker rounds ending at T?” A second supported metric is adjusted round win rate; show the smoothing formula explicitly. Use catalog IDs and enforce the game-specific metric allowlist.

Reuse the same close time, observation grace, exact rational threshold comparison, escrow, payout, and refund implementation. For Siege, use round completion times and first observation timestamps instead of Clash battle timestamps. Freeze platform, rank cohort, patch, side, round filters, and metric version in market rules. A Siege settlement snapshot contains only the matching round evidence.

Require at least 50 accepted rounds for quotes and all Siege settlements; win-rate predictions also require at least 20 selections of the target operator. Freeze these minimums when the market opens. Pick-rate markets may validly resolve at zero picks if round coverage passes. Collection failure, insufficient compatible evidence, or an incompatible source change triggers the existing void/refund rules, never substitution of a different patch or cohort.

## Minimal persistence model

Implement enough structure for correctness; JSON is acceptable for evidence and frozen rules, not for the only copy of balances or stakes.

- `User`: server-generated ID, demo display name, integer available balance.
- `LedgerEntry`: user/account, signed integer units, operation ID, kind, timestamp, related trade/stake/settlement; append-only.
- `Card`, `Cohort`, `PollRun`, `BattleObservation`, `Battle`: catalog and ingestion evidence described above.
- `Snapshot`, `SnapshotBattle`, `CardMetric`: immutable published calculations and membership.
- `Position`: unique `(userId, namespace, cardId)`, integer share quantity, remaining cost basis units.
- `Trade`: side, shares, execution price, snapshot ID, total units, idempotency key.
- `Market`: frozen rules, source/formula versions, opening/closing/target/cutoff times, state.
- `Stake`: user, market, YES/NO, units, idempotency key. Stakes are immutable.
- `Settlement`: unique market ID, outcome/void reason, snapshot ID, actual metric, rule/evidence hashes, totals, algorithm version.
- `Payout`: unique settlement/user, credited units, deterministic allocation evidence.

Store operation payload hashes with idempotency keys: a retry with identical input returns the original result; reuse with different input returns a conflict. Scope keys to user and operation type. Use constraints for nonnegative balances and positions. A signed server session identifies the user; never accept an arbitrary user ID from a request body.

## Virtual asset trading

Create a demo account with **10,000 points** (1,000,000 units), issued exactly once through a recorded grant. Use an HttpOnly, SameSite cookie; Secure in production, verify same-origin mutations, and apply basic request limits. This is demo identity, not production account security. Do not build registration/OAuth during the hackathon.

Support market BUY and SELL of positive whole shares only. No shorts, leverage, limit orders, fees, transfers, or fractional shares. A submitted quote contains the expected snapshot ID; the server verifies it is the latest eligible snapshot for that asset's game and frozen cohort in the account's namespace. Return a fresh quote and conflict if it changed, requiring resubmission instead of silently executing at another price.

Within one transaction: validate session/input/idempotency, verify snapshot and freshness, check funds or holdings, update balance and position, append trade and ledger entries, and save the idempotent result. Concurrent requests must not overspend or oversell. Bound inputs so products stay within safe integer limits; use BigInt where needed for intermediate arithmetic.

For partial sells, allocate cost basis proportionally using integer rounding down; the final sale removes all remaining basis. Show realized P&L and unrealized P&L against the latest valid quote, plus its timestamp. Display unavailable or stale valuation honestly. Trading changes points against the simulated issuer; document the issuer as the ledger counterparty and distinguish these flows from conserved prediction-pool funds.

## Virtual prediction pools

Seed two or three binary markets total, with at least one for each game; defer user-created markets. Example: “Will Valkyrie usage be at least 20% in the sampled 24-hour window ending at T?” Resolve cards by catalog ID, not brittle display names.

Each market freezes at creation: game ID, asset ID, cohort/patch/platform/side where applicable, metric (`usagePct` or `adjustedWinPct` for Clash; `pickRatePct` or `adjustedRoundWinPct` for Siege), operator (`>=` only for MVP), rational threshold, target time, window length, source namespace, formula/filter versions, minimum battle count, minimum non-mirror sample if applicable, entry close, observation cutoff, and failure/refund rules. Show these rules before accepting a stake.

Require `opensAt < closesAt <= targetAt`. Stake acceptance uses server time and requires `now < closesAt`, regardless of worker lag or cached state. Support positive whole-point stakes on YES or NO, capped by available balance. No withdrawals, stake changes, or cash-out. Multiple stakes are allowed and aggregate by user/side.

Atomically debit available points into escrow, append ledger/stake records, and save the idempotent response. Show total YES/NO stakes and each user's exposure. Pool share is stake distribution, not a calibrated forecast probability. Any displayed prospective return is variable until entries close.

State machine: `OPEN -> LOCKED -> SETTLED` or `VOID`. Locking can be materialized by the worker, but entry validation always enforces the closing timestamp. Only the authorized worker/admin can settle; public clients cannot supply outcomes or trigger arbitrary clock changes.

## Deterministic settlement and audit trail

Set observation cutoff to `targetAt + SETTLEMENT_GRACE_SECONDS`. After that cutoff, construct the market's dedicated immutable snapshot using battle time in its frozen window and **first observed at or before cutoff**. Use the frozen cohort/versions and source namespace. Do not resolve from whatever happens to be the latest trading snapshot. Late data after the cutoff never changes a settled outcome.

Persist eligible ingestion evidence continuously so a worker restart can reconstruct the cutoff. If evidence/versions are unavailable, data is insufficient, or no successful collection completed between target and cutoff, void the market with a precise reason and refund every stake. Partial coverage is allowed only if frozen minimums and collection rules pass; report it explicitly. Live and mock records must never mix.

Compare the exact metric fraction against the frozen rational threshold; do not settle on rounded display text. Equality satisfies `>=`. For Clash win-rate markets, enforce the frozen non-mirror minimum (default 20); all Clash markets require the frozen total battle minimum (default 50). Siege markets use the round and operator-selection minimums defined below instead.

Settlement is one atomic transaction guarded by a unique market settlement and state check. It stores evidence, computes allocations, releases escrow into balances, appends ledger/payout entries, and marks the market final. A crash rolls everything back; a retry returns the existing result without additional credits.

For a valid outcome with stakes on both sides, distribute the entire pool to winning-side users proportional to their winning stakes, **including return of principal**. Aggregate each user's winning stakes first. For pool `P`, winning user stake `s_i`, and total winning stake `W`, allocate `floor(P*s_i/W)` units. Distribute leftover units by descending fractional remainder, breaking ties by stable user ID. Use exact integer arithmetic. Store allocation inputs and results.

If either side has zero stake, void/refund the pool as stated in its rules. Empty pools also void cleanly. No fees or house cut. Payouts or refunds must exactly equal escrowed stake units; a void returns each user's full stake on both sides. Never mint points to hide a reconciliation error.

The audit view must expose market rules, actual metric and counts, target/window/cutoff, source mode, snapshot ID, formula version, evidence hash, settlement time, result/reason, pool totals, and per-user payout calculation. Retain underlying evidence locally and provide a sanitized JSON audit export without tokens or session data. Corrections require a separately recorded compensating action; never silently rewrite history.

## Frontend acceptance scope

Build four compact views, responsive enough for laptop and phone:

1. **Market dashboard:** game selector, searchable card/operator list, price, usage or pick rate, adjusted win rate, sample size, freshness, and a small price-history chart or table. Siege adds attacker/defender filtering and cohort/patch labels.
2. **Asset detail:** metric explanation, chart, current quote, BUY/SELL form, holdings, clear rejection reasons, and confirmation of the executed trade.
3. **Portfolio:** available points, committed pool stakes, holdings/cost basis, realized/unrealized P&L, and transaction history. Do not count escrow twice in totals.
4. **Predictions:** frozen market rules, countdown based on server timestamps, stake form, exposure, pool split, settled/void result, and audit details.

Keep a persistent **MOCK DATA / DEMO POINTS** or **LIVE DATA / DEMO POINTS** badge. Add loading, empty, stale, insufficient-data, failed-request, and closed-market states. Disable pending submissions but still enforce server idempotency. Use accessible labels, keyboard navigation, readable contrast, and plain explanations of usage and smoothing. Avoid animation or branding work until the flows function.

## Mock fallback and demo controls

Use deterministic seeded synthetic battle logs shaped like verified provider responses when available; otherwise label the fixture schema as provisional. Feed fixtures through the same normalizer, metrics, snapshot, trade, and settlement code as live input. Do not hand-author metric results and bypass the pipeline.

Seed both games through their own adapters. For Siege include at least six attackers and six defenders, valid five-operator lineups per side, repeat observations, side switches, bans/unavailable picks, rejected rounds, and known outcomes. Seed enough battles/rounds and times for a nonempty historical chart, diverse usage, mirror matches, duplicates from reversed perspectives, draws, invalid modes, and known prediction outcomes. A separate demo clock can advance fixture ingestion and market time through one server-side clock abstraction. Label accelerated time visibly.

Keep mock and live databases separate. Persist the database source namespace and refuse startup if configuration mismatches it. Never revalue a mock holding or settle a mock stake using live data. Live mode always uses wall-clock UTC. Demo clock/reset routes are disabled outside mock demo mode and protected by server-side admin authorization; prefer local CLI commands for the hackathon.

The demo must work without API access. README must explain both paths, real-data gaps, and how to verify live integration later. Use text/card placeholders if image assets are unavailable; artwork must not block the MVP.

## Required verification and acceptance criteria

Use fixed-clock fixtures and a disposable database. Test domain logic plus integration paths that protect balances and evidence; avoid spending time on broad screenshot coverage.

- [ ] Both games work without credentials; switching games changes the catalog and metrics while retaining the same demo wallet and one starting grant.
- [ ] Siege duplicate player observations count a round once; side switches use the current round's side and final selections.
- [ ] Siege fixture `R=100, P=20, W=12` yields 20% pick rate, 60% raw win rate, about 52.8571% adjusted win rate, and a 21.14-point quote.
- [ ] Complete Siege side pick rates sum to 500%; zero picks, zero rounds, and banned operators follow the stated denominator rules.
- [ ] Cross-game asset/quote/metric IDs, mixed patches/platforms, and conflicting round evidence are rejected; each settlement uses its own game's evidence and minimums.
- [ ] Buy/sell an operator and settle a Siege pick-rate pool through the same ledger engine as cards; retry settlement without duplicate credit.
- [ ] Fresh setup runs with mock mode and no API token; seed twice without duplicate grants or records.
- [ ] Re-ingesting the same battle from either player and on later polls preserves one battle and the original observation time; conflicts are quarantined.
- [ ] Non-ranked, malformed, draw, and unknown-mode records are excluded with reasons; evolution variants map to one base card.
- [ ] Window tests cover the inclusive start, exclusive end, and observation cutoff boundaries.
- [ ] A mirror match adds two usage appearances and zero win samples for that card. Zero samples show the documented prior/null behavior.
- [ ] Pure price calculation gives 22.00 points for usage 20% and adjusted wins 55%; test half-up rounding and zero-price rejection.
- [ ] Incomplete snapshots cannot be read; published snapshots cannot be mutated; later ingestion does not alter historical evidence.
- [ ] BUY/SELL updates balance, shares, basis, trade, and ledger together; negative/huge input, insufficient funds/holdings, stale/changed quote, and wrong namespace are rejected.
- [ ] Duplicate requests return the original result. Same key with altered payload conflicts. Concurrent trades/stakes cannot overspend the same account.
- [ ] Stakes are rejected exactly at entry close even if the worker has not materialized LOCKED state.
- [ ] Exact-threshold equality resolves YES; late evidence is excluded; inadequate or failed collection and one-sided pools refund deterministically.
- [ ] A 1,000-unit pool with winning stakes of 100 and 200 units pays 333 and 667 units. Rounding/tie cases conserve every unit.
- [ ] Repeated/concurrent settlement credits once. Injected failure during settlement leaves no partial payouts or final state; retry succeeds once.
- [ ] Audit evidence reproduces the stored metric and outcome; ledger reconciles to each available balance and pool escrow.
- [ ] A manual walkthrough completes login/demo session -> browse -> buy -> sell -> stake -> advance mock time -> settle -> inspect audit -> restart with state preserved.
- [ ] Typecheck, relevant tests, and production build pass; missing live credentials and ingestion failures show useful status without revealing secrets.

## Five-hour delivery plan

| Time | Required outcome | Cut if behind |
| --- | --- | --- |
| 0:00–0:30 | Shared game/asset schema, both mock catalogs, environment checks; start Clash live probe if configured | End API troubleshooting after 15 minutes; use explicit mocks |
| 0:30–1:15 | Both normalizers/metric tests, immutable snapshots, populated card/operator selector | Reduce cohort; omit artwork and fancy charts |
| 1:15–2:15 | Server session, ledger, transactional buy/sell, portfolio, concurrency/idempotency tests | Keep simple table UI; no additional trade types |
| 2:15–3:15 | Frozen prediction rules, escrow/staking, settlement/refunds, audit view and tests | Seed two markets, one per game; no creation UI |
| 3:15–4:00 | Connect all screens, source/freshness states, worker controls, persistent mock demo | Use history table instead of chart library |
| 4:00–4:40 | Full critical-path tests, reconciliation, restart check, production build | Freeze features; fix correctness and startup failures |
| 4:40–5:00 | README, clean demo reset, rehearse, report limitations | Stop polish; preserve runnable deliverable |

Never cut transaction integrity, virtual-only boundaries, mode labeling, deduplication, or settlement auditability to add features. If the full scope does not fit, report incomplete features honestly rather than fabricating completion.

## Three-minute demo

1. Start on a populated mock dashboard; point out synthetic data, virtual points, sampled usage, and price formula.
2. Open a card, buy two shares and sell one. Switch to Siege, show operator pick/round-win rates, and buy an operator using the same demo wallet.
3. Open the Siege pick-rate prediction, read its threshold, cohort, and cutoff, and stake virtual points. Seeded counterparties are labeled demo actors.
4. Advance the mock clock through the authorized local demo control. Run the normal ingestion/snapshot/settlement path.
5. Show the result, exact evidence, and payout or refund. Retry settlement to demonstrate no duplicate credit.
6. End with the pipeline status and honest live-integration limitations. Explain that skill weighting, real auth, scalable deployment, and richer markets are deferred.

## Explicitly deferred

Unverified Siege live integration; Ubisoft Win Delta replication; ban-aware presence; arbitrary map/cohort filtering; real-money/PYUSD functionality; transferable/redeemable points; PageRank/Elo/skill weights; trading-driven prices or an order book; user-created markets; social features; notifications; advanced charting; full anti-abuse defenses; production identity; multi-region deployment; automated provider schema migrations. Add none of these during the five-hour build unless the user explicitly changes scope.
