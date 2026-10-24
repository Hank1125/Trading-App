"""Trading and settlement. Every state change is one transaction with row locks (SELECT ... FOR UPDATE)
on the market and account(s), and every balance change is an append-only LedgerEntry.

See specs/markets/02-trading.md.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from fractions import Fraction

from django.db import IntegrityError, transaction
from django.db.models import F

from markets import lmsr
from markets.models import Account, LedgerEntry, Market, Position, Settlement, Trade

DEMO_GRANT_UNITS = 10_000 * lmsr.UNITS_PER_POINT  # 10,000 points, once per account


class TradeError(Exception):
    def __init__(self, code: str, message: str, quote_units: int | None = None):
        super().__init__(message)
        self.code = code
        self.quote_units = quote_units


# --- accounts -----------------------------------------------------------------------------


def house_account() -> Account:
    house, _ = Account.objects.get_or_create(kind=Account.Kind.HOUSE, defaults={'name': 'Market maker'})
    return house


def demo_account(session_key: str, now: datetime) -> Account:
    """The account for a browser session, with its one-time 10,000-point grant."""
    with transaction.atomic():
        account, created = Account.objects.get_or_create(
            session_key=session_key, defaults={'name': f'Trader {session_key[:6]}'}
        )
        if created:
            _post(account, DEMO_GRANT_UNITS, LedgerEntry.Kind.GRANT, f'grant:{account.pk}', now)
    account.refresh_from_db()
    return account


def _post(account: Account, delta: int, kind: str, op: str, now: datetime, market=None, trade=None) -> None:
    """Append a ledger entry and apply it to the (already locked or new) account."""
    LedgerEntry.objects.create(
        account=account, delta_units=delta, kind=kind, operation_id=op, market=market, trade=trade, created_at=now
    )
    Account.objects.filter(pk=account.pk).update(balance_units=F('balance_units') + delta)


# --- quotes and trades --------------------------------------------------------------------


def state_of(market: Market) -> lmsr.MarketState:
    return lmsr.MarketState(q_up=int(market.q_up), q_down=int(market.q_down), b=Decimal(market.liquidity_b))


def quote_units(market: Market, side: str, action: str, contracts: int) -> int:
    state = state_of(market)
    if action == 'buy':
        return lmsr.buy_cost_units(state, side, contracts)  # type: ignore[arg-type]
    if action == 'sell':
        return lmsr.sell_proceeds_units(state, side, contracts)  # type: ignore[arg-type]
    raise TradeError('bad_action', "action must be 'buy' or 'sell'")


@dataclass(frozen=True)
class TradeResult:
    trade: Trade
    replayed: bool  # True when an idempotent retry returned the original trade


def _payload_hash(market_id: int, side: str, action: str, contracts: int, limit_units: int) -> str:
    raw = json.dumps([market_id, side, action, contracts, limit_units])
    return hashlib.sha256(raw.encode()).hexdigest()


def execute_trade(
    *,
    account_id: int,
    market_id: int,
    side: str,
    action: str,
    contracts: int,
    limit_units: int,
    idempotency_key: str,
    now: datetime,
) -> TradeResult:
    """Buy or sell contracts at the market maker's price.

    `limit_units` is the client's worst acceptable amount: max cost for a buy, min proceeds for
    a sell. If the price moved past it, nothing happens and TradeError('price_moved') carries a
    fresh quote. The same idempotency key returns the original trade; reusing it with a different
    payload is a conflict.
    """
    if side not in lmsr.SIDES:
        raise TradeError('bad_side', "side must be 'up' or 'down'")
    if action not in ('buy', 'sell'):
        raise TradeError('bad_action', "action must be 'buy' or 'sell'")
    if not isinstance(limit_units, int) or isinstance(limit_units, bool) or limit_units < 0:
        raise TradeError('bad_limit', 'limit must be a non-negative whole number of units')
    if not idempotency_key or len(idempotency_key) > 64:
        raise TradeError('bad_key', 'idempotency key must be 1-64 characters')
    payload = _payload_hash(market_id, side, action, contracts, limit_units)

    try:
        with transaction.atomic():
            existing = Trade.objects.filter(account_id=account_id, idempotency_key=idempotency_key).first()
            if existing is not None:
                if existing.payload_hash != payload:
                    raise TradeError('idempotency_conflict', 'this idempotency key was used for a different trade')
                return TradeResult(existing, replayed=True)

            market = Market.objects.select_for_update().get(pk=market_id)
            account = Account.objects.select_for_update().get(pk=account_id, kind=Account.Kind.USER)
            house = Account.objects.select_for_update().get(pk=house_account().pk)

            if market.status != Market.Status.OPEN or now >= market.closes_at:
                raise TradeError('market_closed', 'trading is closed for this market')
            if now < market.opens_at:
                raise TradeError('market_not_open', 'this market has not opened yet')

            position, _ = Position.objects.select_for_update().get_or_create(account=account, market=market)
            held = position.up_contracts if side == 'up' else position.down_contracts
            if action == 'sell' and isinstance(contracts, int) and contracts > held:
                raise TradeError('insufficient_contracts', f'you hold {held} {side.upper()} contracts')
            try:
                units = quote_units(market, side, action, contracts)
            except lmsr.LmsrError as e:
                raise TradeError('bad_contracts', str(e)) from None

            if action == 'buy':
                if units > limit_units:
                    raise TradeError('price_moved', 'price moved above your limit', quote_units=units)
                if units > account.balance_units:
                    raise TradeError('insufficient_funds', 'not enough points')
                delta = contracts
            else:
                if units < limit_units:
                    raise TradeError('price_moved', 'price moved below your limit', quote_units=units)
                delta = -contracts

            new_state = lmsr.apply(state_of(market), side, delta)  # type: ignore[arg-type]
            market.q_up, market.q_down = new_state.q_up, new_state.q_down
            market.save(update_fields=['q_up', 'q_down'])

            if side == 'up':
                position.up_contracts += delta
            else:
                position.down_contracts += delta
            position.net_cost_units += units if action == 'buy' else -units
            position.save()

            trade = Trade.objects.create(
                account=account,
                market=market,
                side=side,
                action=action,
                contracts=contracts,
                units=units,
                up_price_after=lmsr.display_price(new_state, 'up'),
                idempotency_key=idempotency_key,
                payload_hash=payload,
                created_at=now,
            )
            sign = -1 if action == 'buy' else 1
            _post(account, sign * units, LedgerEntry.Kind.TRADE, f'trade:{trade.pk}', now, market, trade)
            _post(house, -sign * units, LedgerEntry.Kind.TRADE, f'trade:{trade.pk}', now, market, trade)
            return TradeResult(trade, replayed=False)
    except IntegrityError:
        # A concurrent request with the same idempotency key won the race; return its result.
        existing = Trade.objects.filter(account_id=account_id, idempotency_key=idempotency_key).first()
        if existing is None:
            raise
        if existing.payload_hash != payload:
            raise TradeError('idempotency_conflict', 'this idempotency key was used for a different trade') from None
        return TradeResult(existing, replayed=True)


# --- settlement ---------------------------------------------------------------------------


def decide(start: Fraction, end: Fraction | None) -> tuple[str, str]:
    """Pure outcome rule: UP if end > start, DOWN if end < start, VOID if equal or unknown."""
    if end is None:
        return Settlement.Outcome.VOID, 'no data at window end'
    if end > start:
        return Settlement.Outcome.UP, 'stat rose'
    if end < start:
        return Settlement.Outcome.DOWN, 'stat fell'
    return Settlement.Outcome.VOID, 'stat unchanged'


def close_market(market_id: int, now: datetime) -> None:
    Market.objects.filter(pk=market_id, status=Market.Status.OPEN, closes_at__lte=now).update(
        status=Market.Status.CLOSED
    )


def settle_market(
    market_id: int, *, end: tuple[int, int] | None, evidence: dict, now: datetime
) -> Settlement:
    """Pay winners 100 points per contract, or refund net cost on VOID. Exactly once per market."""
    with transaction.atomic():
        market = Market.objects.select_for_update().get(pk=market_id)
        existing = Settlement.objects.filter(market=market).first()
        if existing is not None:
            return existing
        if now < market.settles_after:
            raise TradeError('too_early', 'market cannot settle before its settlement time')

        start = Fraction(market.start_numerator, market.start_denominator)
        end_value = Fraction(end[0], end[1]) if end and end[1] > 0 else None
        outcome, reason = decide(start, end_value)

        house = Account.objects.select_for_update().get(pk=house_account().pk)
        positions = list(
            Position.objects.select_for_update().filter(market=market).select_related('account').order_by('account_id')
        )
        total = 0
        for p in positions:
            if outcome == Settlement.Outcome.VOID:
                amount, kind = max(p.net_cost_units, 0), LedgerEntry.Kind.REFUND
            else:
                held = p.up_contracts if outcome == Settlement.Outcome.UP else p.down_contracts
                amount, kind = held * lmsr.PAYOUT_UNITS, LedgerEntry.Kind.PAYOUT
            if amount:
                Account.objects.select_for_update().get(pk=p.account_id)
                _post(p.account, amount, kind, f'settle:{market.pk}', now, market)
                _post(house, -amount, kind, f'settle:{market.pk}:{p.account_id}', now, market)
                total += amount

        settlement = Settlement.objects.create(
            market=market,
            outcome=outcome,
            reason=reason,
            end_numerator=end[0] if end else None,
            end_denominator=end[1] if end else None,
            evidence=evidence,
            total_paid_units=total,
            settled_at=now,
        )
        market.status = Market.Status.VOID if outcome == Settlement.Outcome.VOID else Market.Status.SETTLED
        market.save(update_fields=['status'])
        return settlement


# --- read helpers -------------------------------------------------------------------------


def sides_summary(market: Market) -> dict:
    """How many people hold UP vs DOWN, and how many contracts each side has outstanding."""
    positions = Position.objects.filter(market=market)
    return {
        'up_people': positions.filter(up_contracts__gt=0).count(),
        'down_people': positions.filter(down_contracts__gt=0).count(),
        'up_contracts': int(market.q_up),
        'down_contracts': int(market.q_down),
    }
