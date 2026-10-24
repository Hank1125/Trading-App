from datetime import UTC, datetime, timedelta
from fractions import Fraction

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.siege.fixtures import load_catalog_fixture, load_pages
from app.siege.ingest import ingest_revision, seed_catalog
from app.siege.models import MapObservation
from app.siege.stats import Scope, all_stats_at, stat_at

T0 = datetime(2026, 11, 6, 0, 0, tzinfo=UTC)
NS = "replay:test"
SCOPE = Scope(NS, ("P",))


def hours(n: float) -> datetime:
    return T0 + timedelta(hours=n)


@pytest.fixture
def seeded(db: Session) -> Session:
    seed_catalog(db, load_catalog_fixture())
    return db


def ingest(db: Session, wikitext: str, revid: int, at: datetime, page: str = "P", namespace: str = NS):
    return ingest_revision(
        db, namespace=namespace, page=page, revid=revid, revision_timestamp="t", wikitext=wikitext, now=at
    )


def map_block(order: int, name: str, bans1: str, bans2: str, finished: bool = True) -> str:
    status = "true" if finished else ""
    rounds = "|t1atk=4|t1def=3|t2atk=1|t2def=1" if finished else ""
    b1 = "".join(f"|t1ban{i}={b}" for i, b in enumerate(bans1.split(","), 1) if b)
    b2 = "".join(f"|t2ban{i}={b}" for i, b in enumerate(bans2.split(","), 1) if b)
    return f"|map{order}={{{{Map|map={name}|finished={status}{b1}{b2}{rounds}}}}}"


def page(*maps: str, teams=("Team Falcons", "FURIA")) -> str:
    return (
        f"{{{{Match|date=2026-11-06|finished=true|opponent1={{{{TeamOpponent|{teams[0]}}}}}"
        f"|opponent2={{{{TeamOpponent|{teams[1]}}}}}{''.join(maps)}}}}}"
    )


# --- real May 2026 Major ------------------------------------------------------------------


def test_real_fixture_final_values(seeded: Session):
    now = datetime(2026, 10, 24, tzinfo=UTC)
    pages = load_pages("blast-2026-may")
    for p in pages:
        ingest(seeded, p.wikitext, p.revid, now, page=p.title)
    scope = Scope(NS, tuple(p.title for p in pages))
    assert stat_at(seeded, scope, "operator_ban_rate", "Mira", now).fraction == Fraction(66, 84)
    assert stat_at(seeded, scope, "operator_ban_rate", "Valkyrie", now).fraction == Fraction(10, 84)
    assert stat_at(seeded, scope, "map_play_rate", "Clubhouse", now).fraction == Fraction(13, 84)
    top3 = [(v.subject, v.numerator) for v in all_stats_at(seeded, scope, "operator_ban_rate", now)[:3]]
    assert top3 == [("Mira", 66), ("Kaid", 63), ("Montagne", 58)]
    plays = all_stats_at(seeded, scope, "map_play_rate", now)
    assert sum(v.numerator for v in plays) == 84  # every finished map is on exactly one map


# --- time travel --------------------------------------------------------------------------


def test_nothing_is_known_before_it_is_observed(seeded: Session):
    ingest(seeded, page(map_block(1, "Bank", "Mira", "Kaid")), 1, hours(2))
    before = stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(1))
    assert before.denominator == 0 and before.fraction is None and before.percent is None
    assert stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(2)).fraction == 1


def test_a_map_counts_from_when_it_was_first_seen_finished(seeded: Session):
    ingest(
        seeded, page(map_block(1, "Bank", "Mira", "Kaid"), map_block(2, "Lair", "", "", False)), 1, hours(1)
    )
    ingest(
        seeded, page(map_block(1, "Bank", "Mira", "Kaid"), map_block(2, "Lair", "Ash", "Kaid")), 2, hours(2)
    )
    at_1h = stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(1.5))
    at_2h = stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(2))
    assert (at_1h.numerator, at_1h.denominator) == (1, 1)
    assert (at_2h.numerator, at_2h.denominator) == (1, 2)  # Mira 100% -> 50% when Lair finished
    assert stat_at(seeded, SCOPE, "operator_ban_rate", "Kaid", hours(2)).fraction == 1


def test_unchanged_reingest_adds_no_observations(seeded: Session):
    text = page(map_block(1, "Bank", "Mira", "Kaid"))
    ingest(seeded, text, 1, hours(1))
    ingest(seeded, text, 2, hours(2))
    assert seeded.scalar(select(func.count()).select_from(MapObservation)) == 1


def test_a_later_correction_does_not_rewrite_earlier_values(seeded: Session):
    ingest(seeded, page(map_block(1, "Bank", "Mira", "Kaid")), 1, hours(1))
    ingest(seeded, page(map_block(1, "Bank", "Azami", "Kaid")), 2, hours(3))  # editor fixes a ban
    assert stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(2)).fraction == 1
    assert stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(3)).fraction == 0
    assert stat_at(seeded, SCOPE, "operator_ban_rate", "Azami", hours(3)).fraction == 1


def test_a_map_removed_from_the_page_stops_counting_from_then_on(seeded: Session):
    two = page(map_block(1, "Bank", "Mira", ""), map_block(2, "Lair", "Ash", ""))
    ingest(seeded, two, 1, hours(1))
    ingest(seeded, page(map_block(1, "Bank", "Mira", "")), 2, hours(2))
    assert stat_at(seeded, SCOPE, "map_play_rate", "Lair", hours(1)).fraction == Fraction(1, 2)
    after = stat_at(seeded, SCOPE, "map_play_rate", "Lair", hours(2))
    assert (after.numerator, after.denominator) == (0, 1)


def test_operator_banned_by_both_teams_counts_once(seeded: Session):
    ingest(seeded, page(map_block(1, "Bank", "Mira,Kaid", "Mira")), 1, hours(1))
    assert stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(1)).numerator == 1


# --- scope --------------------------------------------------------------------------------


def test_scope_excludes_other_pages_and_namespaces(seeded: Session):
    ingest(seeded, page(map_block(1, "Bank", "Mira", "")), 1, hours(1), page="P")
    ingest(seeded, page(map_block(1, "Lair", "Ash", "")), 1, hours(1), page="Other")
    ingest(seeded, page(map_block(1, "Lair", "Ash", "")), 1, hours(1), page="P", namespace="live")
    v = stat_at(seeded, SCOPE, "map_play_rate", "Bank", hours(1))
    assert (v.numerator, v.denominator) == (1, 1)


def test_values_carry_their_evidence(seeded: Session):
    ingest(seeded, page(map_block(1, "Bank", "Mira", ""), map_block(2, "Lair", "Ash", "")), 1, hours(1))
    v = stat_at(seeded, SCOPE, "operator_ban_rate", "Mira", hours(1))
    obs_ids = set(seeded.scalars(select(MapObservation.id)))
    assert set(v.observation_ids) == obs_ids and len(obs_ids) == 2
    assert v.percent == 50.0
