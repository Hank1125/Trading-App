"""Pure LMSR (logarithmic market scoring rule) market maker for binary UP/DOWN markets.

See specs/markets/01-lmsr.md. No ORM access, so everything can be unit-tested directly.

- A winning contract pays PAYOUT_POINTS (100) virtual points; a losing one pays 0.
- The market maker always quotes: cost C(q) = PAYOUT * b * ln(e^(q_up/b) + e^(q_down/b)),
  where q_up/q_down are contracts outstanding and b is the liquidity (larger b = smaller price moves).
- Money is integer units (1 point = 100 units). Buys round UP, sells round DOWN, so rounding
  never favours the trader and the house's loss is bounded by PAYOUT * b * ln(2).
"""

from dataclasses import dataclass, replace
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal, localcontext
from typing import Literal

Side = Literal['up', 'down']
SIDES: tuple[Side, Side] = ('up', 'down')

UNITS_PER_POINT = 100
PAYOUT_POINTS = 100
PAYOUT_UNITS = PAYOUT_POINTS * UNITS_PER_POINT

MIN_B = Decimal(1)
MAX_B = Decimal(100_000)
MAX_CONTRACTS_PER_TRADE = 10_000
MAX_OUTSTANDING = 10_000_000

_PRECISION = 60


class LmsrError(ValueError):
    pass


@dataclass(frozen=True)
class MarketState:
    q_up: int
    q_down: int
    b: Decimal

    def __post_init__(self):
        if not isinstance(self.b, Decimal) or not (MIN_B <= self.b <= MAX_B):
            raise LmsrError(f'b must be a Decimal in [{MIN_B}, {MAX_B}]')
        for q in (self.q_up, self.q_down):
            if not isinstance(q, int) or isinstance(q, bool) or not (0 <= q <= MAX_OUTSTANDING):
                raise LmsrError('outstanding contracts must be whole numbers within bounds')

    def q(self, side: Side) -> int:
        return self.q_up if side == 'up' else self.q_down


def _cost_points(q_up: int, q_down: int, b: Decimal) -> Decimal:
    """C(q) in points, computed with log-sum-exp for numerical stability."""
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        hi = Decimal(max(q_up, q_down))
        total = ((Decimal(q_up) - hi) / b).exp() + ((Decimal(q_down) - hi) / b).exp()
        return PAYOUT_POINTS * (hi + b * total.ln())


def price(state: MarketState, side: Side) -> Decimal:
    """Instantaneous probability-like price of one contract on `side`, in (0, 1)."""
    _check_side(side)
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        diff = Decimal(state.q_down - state.q_up) / state.b
        p_up = 1 / (1 + diff.exp())
        return p_up if side == 'up' else 1 - p_up


def display_price(state: MarketState, side: Side) -> int:
    """Price in points per contract (1-99), as shown in the UI. Never shows 0 or 100."""
    shown = int((price(state, side) * PAYOUT_POINTS).quantize(Decimal(1), rounding=ROUND_HALF_UP))
    return min(max(shown, 1), PAYOUT_POINTS - 1)


def _check_side(side: str) -> None:
    if side not in SIDES:
        raise LmsrError("side must be 'up' or 'down'")


def _check_contracts(n: int) -> None:
    if not isinstance(n, int) or isinstance(n, bool) or not (1 <= n <= MAX_CONTRACTS_PER_TRADE):
        raise LmsrError(f'contracts must be a whole number from 1 to {MAX_CONTRACTS_PER_TRADE}')


def _to_units(points: Decimal, rounding: str) -> int:
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return int((points * UNITS_PER_POINT).quantize(Decimal(1), rounding=rounding))


def buy_cost_units(state: MarketState, side: Side, contracts: int) -> int:
    """Units the trader pays to buy `contracts` on `side` (rounded up)."""
    _check_side(side)
    _check_contracts(contracts)
    after = apply(state, side, contracts)
    delta = _cost_points(after.q_up, after.q_down, state.b) - _cost_points(state.q_up, state.q_down, state.b)
    return _to_units(delta, ROUND_CEILING)


def sell_proceeds_units(state: MarketState, side: Side, contracts: int) -> int:
    """Units the trader receives for selling `contracts` on `side` back (rounded down)."""
    _check_side(side)
    _check_contracts(contracts)
    if contracts > state.q(side):
        raise LmsrError('cannot sell more contracts than are outstanding')
    after = apply(state, side, -contracts)
    delta = _cost_points(state.q_up, state.q_down, state.b) - _cost_points(after.q_up, after.q_down, state.b)
    return _to_units(delta, ROUND_FLOOR)


def apply(state: MarketState, side: Side, delta: int) -> MarketState:
    """New state after `delta` contracts on `side` are bought (+) or sold back (-)."""
    _check_side(side)
    if side == 'up':
        return replace(state, q_up=state.q_up + delta)
    return replace(state, q_down=state.q_down + delta)


def max_subsidy_units(b: Decimal) -> int:
    """Worst-case market-maker loss for liquidity b: PAYOUT * b * ln(2), in units (rounded up)."""
    with localcontext() as ctx:
        ctx.prec = _PRECISION
        return _to_units(PAYOUT_POINTS * b * Decimal(2).ln(), ROUND_CEILING)
