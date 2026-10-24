"""Pure cr-price-v1 metric math. See specs/clash-royale/02-metrics.md.

No ORM access here, so everything can be unit-tested directly.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

FORMULA_VERSION = 'cr-price-v1'
WINDOW = timedelta(days=7)
K = 100
LOW_SAMPLE_THRESHOLD = 200

_Q = Decimal('0.0001')


@dataclass(frozen=True)
class CardMetrics:
    total_appearances: int
    appearances: int
    wins: int
    losses: int
    draws: int
    usage_pct: Decimal
    win_rate: Decimal | None
    adj_win_rate: Decimal
    price: Decimal
    is_low_sample: bool


def _q(value):
    return value.quantize(_Q, rounding=ROUND_HALF_UP)


def compute_card_metrics(total_appearances, appearances, wins, losses, draws):
    """Metrics for one card from its counts in the window. total_appearances must be > 0."""
    if total_appearances <= 0:
        raise ValueError('total_appearances must be positive')
    if wins + losses + draws != appearances:
        raise ValueError('wins + losses + draws must equal appearances')

    decided = wins + losses
    usage = Decimal(100) * appearances / total_appearances
    win_rate = Decimal(100) * wins / decided if decided else None
    adj = Decimal(100) * (wins + Decimal(K) / 2) / (decided + K)
    # Price uses unrounded inputs; only the stored values are rounded.
    price = usage * adj / 50
    return CardMetrics(
        total_appearances=total_appearances,
        appearances=appearances,
        wins=wins,
        losses=losses,
        draws=draws,
        usage_pct=_q(usage),
        win_rate=_q(win_rate) if win_rate is not None else None,
        adj_win_rate=_q(adj),
        price=_q(price),
        is_low_sample=appearances < LOW_SAMPLE_THRESHOLD,
    )


def tally_decks(decks):
    """Count appearances per card from (card_ids, result) pairs, result in 'W'/'L'/'D'.

    Returns (total_appearances, {card_id: (appearances, wins, losses, draws)}).
    """
    counts = {}
    total = 0
    for card_ids, result in decks:
        total += 1
        for card_id in set(card_ids):
            n, w, l, d = counts.get(card_id, (0, 0, 0, 0))
            counts[card_id] = (
                n + 1,
                w + (result == 'W'),
                l + (result == 'L'),
                d + (result == 'D'),
            )
    return total, counts


def result_for(own_crowns, opponent_crowns):
    if own_crowns > opponent_crowns:
        return 'W'
    if own_crowns < opponent_crowns:
        return 'L'
    return 'D'


def hour_floor(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)
