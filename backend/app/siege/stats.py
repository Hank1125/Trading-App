"""Siege pro-meta stats as known at a point in time, from the append-only map observation log.

`value at T` only uses map data first observed at or before T, so a stat's history (and every
market settled on it) is reproducible: later Liquipedia edits only affect values after they land.
"""

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from fractions import Fraction
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.siege.models import MapObservation, Match

StatKind = Literal["operator_ban_rate", "map_play_rate"]

FORMULA_VERSIONS: dict[StatKind, str] = {
    "operator_ban_rate": "pro-ban-rate-v1",  # finished maps where banned by either team / finished maps
    "map_play_rate": "map-play-rate-v1",  # finished maps played on this map / finished maps
}


@dataclass(frozen=True)
class Scope:
    """Which evidence a stat counts: one data namespace and the event's Liquipedia pages."""

    namespace: str
    pages: tuple[str, ...]


@dataclass(frozen=True)
class StatValue:
    kind: StatKind
    subject: str
    as_of: datetime
    numerator: int
    denominator: int
    observation_ids: tuple[int, ...]  # the map observations counted, for audit/evidence

    @property
    def fraction(self) -> Fraction | None:
        return Fraction(self.numerator, self.denominator) if self.denominator else None

    @property
    def percent(self) -> float | None:
        """Display only (percentage points). Settlement must compare `fraction`, never this."""
        f = self.fraction
        return None if f is None else float(100 * f)


def finished_maps_at(session: Session, scope: Scope, as_of: datetime) -> list[tuple[int, dict[str, Any]]]:
    """(observation id, map content) for every map slot whose latest observation by `as_of` is finished."""
    latest = (
        select(MapObservation)
        .join(Match, Match.id == MapObservation.match_id)
        .where(
            Match.namespace == scope.namespace,
            Match.page.in_(scope.pages),
            MapObservation.observed_at <= as_of,
        )
        .order_by(
            MapObservation.match_id,
            MapObservation.order,
            MapObservation.observed_at.desc(),
            MapObservation.id.desc(),
        )
        .distinct(MapObservation.match_id, MapObservation.order)
    )
    return [(o.id, o.content) for o in session.scalars(latest) if o.status == "finished"]


def _banned(content: dict[str, Any]) -> set[str]:
    return set(content["t1_bans"]) | set(content["t2_bans"])


def stat_at(session: Session, scope: Scope, kind: StatKind, subject: str, as_of: datetime) -> StatValue:
    maps = finished_maps_at(session, scope, as_of)
    if kind == "operator_ban_rate":
        hits = [oid for oid, c in maps if subject in _banned(c)]
    else:
        hits = [oid for oid, c in maps if c["map"] == subject]
    return StatValue(
        kind=kind,
        subject=subject,
        as_of=as_of,
        numerator=len(hits),
        denominator=len(maps),
        observation_ids=tuple(sorted(oid for oid, _ in maps)),
    )


def all_stats_at(session: Session, scope: Scope, kind: StatKind, as_of: datetime) -> list[StatValue]:
    """Every subject seen so far for this stat, highest first (ties by name). One query."""
    maps = finished_maps_at(session, scope, as_of)
    counts: Counter[str] = Counter()
    for _, c in maps:
        counts.update(_banned(c) if kind == "operator_ban_rate" else [c["map"]])
    ids = tuple(sorted(oid for oid, _ in maps))
    values = [StatValue(kind, subject, as_of, n, len(maps), ids) for subject, n in counts.items()]
    return sorted(values, key=lambda v: (-v.numerator, v.subject))
