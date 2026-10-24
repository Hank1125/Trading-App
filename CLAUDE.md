# Meta Market — Project Scope

## What we are building

An app where people trade on the gaming meta for **Clash Royale** and **Rainbow Six Siege**.

- **Clash Royale:** track card usage rates and win rates for the top 1000 players.
- **Rainbow Six Siege:** track operator pick rates and win rates.
- Users buy and sell virtual shares whose reference prices reflect these metrics.
- Users can also stake virtual points on predictions about future metrics, such as “Will this operator's pick rate exceed 25%?”
- Show metric history, prices, holdings, and prediction results so users can understand their decisions.

Start with virtual points only. No PYUSD, real-money betting, deposits, withdrawals, or redeemable rewards without explicit authorization and separate scope.

## Product principles

- Keep the first version small, understandable, and usable across both games.
- Share the trading and prediction infrastructure, but calculate each game's metrics separately.
- Clearly define usage/pick-rate and win-rate denominators. For Siege, distinguish attacker/defender sides and round wins from match wins; do not label Win Delta as win rate.
- Make prices explainable. The initial direction is usage/pick rate adjusted by win rate; finalize and version the formula when implementing metrics.
- Clearly label real versus mock data, sample sizes, and freshness. Do not present incomplete or synthetic data as live population statistics.
- Keep trading shares separate from predicting a metric's future outcome. Explain both simply in the UI.

## Development stages

### 1. Foundation and demo data

Set up the app, game selector, card/operator catalog, and persistent storage. Use realistic, clearly labeled mock data for both games so development does not depend on external access.

**Done when:** the app runs locally and users can browse cards and operators with sample metrics.

### 2. Data and metrics

Add game-specific ingestion, validation, deduplication, usage/pick-rate calculations, win rates, and timestamped snapshots. Verify source access and definitions before enabling live data. Keep mock mode available.

**Done when:** repeated ingestion does not double-count records, calculations have tests, and the UI shows each metric's source, period, sample size, and freshness.

### 3. Virtual trading

Add a virtual-points balance, metric-based share prices, buy/sell actions, holdings, and transaction history. Keep balance and holding updates atomic; prevent overspending, overselling, and duplicate execution.

**Done when:** users can buy and sell cards/operators, see correct balances and holdings, and retain their state after restarting the app.

### 4. Meta predictions

Add simple YES/NO pools for future usage/pick rates or win rates. Freeze the metric, threshold, data source, time window, entry deadline, and settlement rules before accepting stakes. Resolve from saved evidence, record payouts, and refund when required data is unavailable. Repeated settlement must never pay twice.

**Done when:** users can stake points, see a prediction close and settle, and inspect the result, supporting metric, and payout or refund.

### 5. Polish and demo

Connect both games into a clear dashboard and portfolio. Add useful loading, empty, stale-data, and error states. Document setup and rehearse the full flow.

**Done when:** a fresh setup can demonstrate browsing, trading, predicting, and settlement for both games without live API access.

## Working instructions for Claude Code

1. Read the existing repository instructions and code before making changes. Preserve unrelated work.
2. Work in small, reviewable changes within the current stage. Avoid unnecessary dependencies, abstractions, or features.
3. **After every logical change, explain what changed, why, and how it was verified.** Keep the explanation short and mention anything still incomplete.
4. **Test before every commit.** Run tests relevant to the change, plus applicable type/lint checks. Run the production build for integration milestones. Add regression tests for bugs and meaningful tests for metrics, balances, trades, and settlement.
5. Do not commit with failing required checks. If a check cannot run, explain the blocker and leave the change uncommitted. Never claim a test passed unless it ran successfully.
6. Make focused commits only when requested or already authorized. Summarize the changes and test results with each commit.
7. Keep secrets and authoritative pricing, balance updates, and settlement logic on the server. Validate inputs and make retries safe.
8. Never silently mix mock and live data, change an active prediction's rules, or rewrite settled results.
9. Explain material scope changes or blockers promptly. Ask only when a decision changes the intended product or needs authorization; handle routine implementation choices independently.
10. At the end of each stage, summarize what works, what was tested, and what comes next.

## Five-hour MVP boundary

Aim for one working path through all stages with both games, a shared virtual wallet, simple buy/sell trading, and a small number of prediction pools. Prioritize correctness and a reliable demo over breadth.

Timebox external data integration; use labeled mock data if access is blocked. Defer advanced charts, skill weighting, order books, user-created markets, social features, and production-scale infrastructure. Do not cut balance integrity, testing, or settlement evidence to add features.
