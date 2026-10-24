"""Stat values for markets, read from the Clash Royale tables in the shared database.

A value "at T" only uses data known by T, so market start/end values are reproducible:
a card's price at T is the latest `CardMetricSnapshot` whose window ended by T.
"""

from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction

from clashroyale.models import CardMetricSnapshot

FORMULA_VERSIONS = {
    ('clash_royale', 'card_price'): 'cr-price-v1',
}


@dataclass(frozen=True)
class StatPoint:
    numerator: int
    denominator: int
    evidence: dict = field(default_factory=dict)

    @property
    def fraction(self) -> Fraction:
        return Fraction(self.numerator, self.denominator)

    @property
    def percent(self) -> float:
        return float(100 * self.fraction)


def value_at(game: str, stat_kind: str, subject: str, scope: dict, as_of: datetime) -> StatPoint | None:
    if game == 'clash_royale' and stat_kind == 'card_price':
        snap = (
            CardMetricSnapshot.objects.filter(
                card__name=subject, source=scope.get('source', 'live'), window_end__lte=as_of
            )
            .order_by('-window_end', '-id')
            .first()
        )
        if snap is None:
            return None
        f = Fraction(snap.price)
        evidence = {'card_metric_snapshot_id': snap.pk, 'price': str(snap.price), 'as_of': snap.window_end.isoformat()}
        return StatPoint(f.numerator, f.denominator, evidence)
    raise ValueError(f'unsupported stat {game}/{stat_kind}')


def top_subjects(game: str, stat_kind: str, scope: dict, as_of: datetime, n: int | None) -> list[str]:
    """The n subjects (all if n is None) with the highest value at `as_of`, ties by name: which get markets."""
    if game == 'clash_royale':
        latest = (
            CardMetricSnapshot.objects.filter(source=scope.get('source', 'live'), window_end__lte=as_of)
            .order_by('-window_end')
            .values_list('window_end', flat=True)
            .first()
        )
        if latest is None:
            return []
        qs = CardMetricSnapshot.objects.filter(source=scope.get('source', 'live'), window_end=latest)
        return list(qs.order_by('-price', 'card__name').values_list('card__name', flat=True)[:n])
    raise ValueError(f'unsupported game {game}')
