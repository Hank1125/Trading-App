# Markets 02 — Accounts, trading and settlement

Code: `markets/models.py`, `markets/services.py`. Virtual points only.

## Accounts and ledger
- Each browser session gets a demo `Account` with a **10,000-point grant, recorded once**.
- A single **house** account is the market maker's counterparty. Its balance may go negative, bounded per market by `100 · b · ln 2`.
- Every balance change is an append-only `LedgerEntry`, and `(account, operation_id)` is unique.
  - Each account's balance equals the sum of its entries.
  - The sum of all balances equals the total grants: points are conserved.

## Markets
- A market is one stat (`game`, `stat_kind`, `subject`, `scope`, `formula_version`) over one window (`hourly`/`daily`/`weekly`).
- The start value (`start_numerator / start_denominator`) is frozen when the market is created.
- The rules never change after creation.
- State: `open` → `closed` → `settled` or `void`.

## Trading (`execute_trade`)
One transaction, with `SELECT … FOR UPDATE` on the market, the account and the house:
1. Server time must be within `[opens_at, closes_at)`. This is enforced even if the worker hasn't marked the market closed yet.
2. Price comes from LMSR (`01-lmsr.md`). The client sends a **limit** (max cost for a buy, min proceeds for a sell). If the price moved past it, the trade is rejected with code `price_moved` and a fresh quote.
3. The trade is rejected on insufficient funds or contracts, or bad side, count or limit.
4. The market's `q`, the position, the trade and two ledger entries (user and house) are written together.
5. **Idempotency:** the same `(account, key)` returns the original trade. The same key with a different payload returns `idempotency_conflict`.

## Settlement (`settle_market`)
- Not allowed before `settles_after` (window end plus grace). It runs at most once per market (unique `Settlement`), so retries return the existing result.
- Outcome compares **exact fractions**: `end > start` → **UP**, `end < start` → **DOWN**, equal or unknown → **VOID**.
- UP or DOWN: winning contracts pay **100 points** each.
- VOID: each user gets their **net cost** back (buys minus sells, never below 0).
- Error codes: `market_closed`, `market_not_open`, `price_moved`, `insufficient_funds`, `insufficient_contracts`, `bad_contracts`, `bad_side`, `bad_action`, `bad_limit`, `bad_key`, `idempotency_conflict`, `too_early`.
