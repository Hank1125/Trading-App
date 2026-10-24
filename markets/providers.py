"""Stat values for markets, read from each game's own tables in the shared database.

A value "at T" only uses data known by T, so market start/end values are reproducible.
- Siege: point-in-time ban/play rates from the append-only `siege_map_observation` log written by
  the Siege backend (backend/app/siege/stats.py implements the same rule; this is a read-only SQL port).
- Clash Royale: the latest `CardMetricSnapshot` price whose window ended by T.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from fractions import Fraction

from django.db import DatabaseError, connection, transaction

from clashroyale.models import CardMetricSnapshot

FORMULA_VERSIONS = {
    ('siege', 'operator_ban_rate'): 'pro-ban-rate-v1',
    ('siege', 'map_play_rate'): 'map-play-rate-v1',
    ('clash_royale', 'card_price'): 'cr-price-v1',
}

_SIEGE_LATEST_MAPS = """
    SELECT DISTINCT ON (o.match_id, o."order") o.id, o.status, o.content
    FROM siege_map_observation o
    JOIN siege_match m ON m.id = o.match_id
    WHERE m.namespace = %s AND m.page = ANY(%s) AND o.observed_at <= %s
    ORDER BY o.match_id, o."order", o.observed_at DESC, o.id DESC
"""


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


def _siege_finished_maps(scope: dict, as_of: datetime) -> list[tuple[int, dict]]:
    try:
        with transaction.atomic(), connection.cursor() as cur:  # savepoint: a missing table can't break callers
            cur.execute(_SIEGE_LATEST_MAPS, [scope['namespace'], list(scope['pages']), as_of])
            rows = cur.fetchall()
    except DatabaseError:  # Siege tables not migrated in this database
        return []
    # Django's raw cursor returns jsonb as text.
    return [(oid, json.loads(c) if isinstance(c, str) else c) for oid, status, c in rows if status == 'finished']


def _siege_counts(kind: str, maps: list[tuple[int, dict]]) -> Counter:
    counts: Counter = Counter()
    for _, c in maps:
        counts.update(set(c['t1_bans']) | set(c['t2_bans']) if kind == 'operator_ban_rate' else [c['map']])
    return counts


def value_at(game: str, stat_kind: str, subject: str, scope: dict, as_of: datetime) -> StatPoint | None:
    if game == 'siege':
        maps = _siege_finished_maps(scope, as_of)
        if not maps:
            return None
        n = _siege_counts(stat_kind, maps)[subject]
        return StatPoint(n, len(maps), {'map_observation_ids': sorted(oid for oid, _ in maps)})
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


def top_subjects(game: str, stat_kind: str, scope: dict, as_of: datetime, n: int) -> list[str]:
    """The n subjects with the highest value at `as_of` (ties by name) — which ones get markets."""
    if game == 'siege':
        counts = _siege_counts(stat_kind, _siege_finished_maps(scope, as_of))
        return [s for s, _ in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]
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
