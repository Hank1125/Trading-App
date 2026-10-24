from datetime import UTC, datetime

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import Base
from app.siege.fixtures import load_catalog_fixture, load_pages
from app.siege.ingest import ingest_revision, seed_catalog
from app.siege.models import (
    Correction,
    MapPlayed,
    Match,
    Operator,
    OperatorBan,
    PageRevision,
    Quarantine,
    Team,
)

NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)
NS = "replay:test"


@pytest.fixture
def seeded(db: Session) -> Session:
    seed_catalog(db, load_catalog_fixture())
    return db


def ingest(db: Session, wikitext: str, revid: int, page: str = "P", namespace: str = NS):
    return ingest_revision(
        db, namespace=namespace, page=page, revid=revid, revision_timestamp="t", wikitext=wikitext, now=NOW
    )


def match_page(
    *, date="2026-11-06 - 10:00 {{Abbr/JST}}", t1_bans="Mira|t1ban2=Kaid", status="true", rounds="2"
):
    return (
        f"{{{{Match|date={date}|finished={status}"
        "|opponent1={{TeamOpponent|Team Falcons}}|opponent2={{TeamOpponent|FURIA}}"
        "|mapveto={{MapVeto|types=ban,decider|t1map1=Bank|t2map1=Lair|decider=Chalet}}"
        f"|map1={{{{Map|map=Chalet|finished={status}|t1ban1={t1_bans}|t2ban1=Valk|t2ban2=Mira"
        f"|t1firstside=atk|t1atk=4|t1def=3|t2atk={rounds}|t2def=0}}}}}}}}"
    )


def count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


# --- migration ----------------------------------------------------------------------------


def test_migration_matches_the_models(db: Session):
    diff = compare_metadata(MigrationContext.configure(db.connection()), Base.metadata)
    assert diff == []


def test_seed_catalog_is_idempotent(db: Session):
    assert seed_catalog(db, load_catalog_fixture()) == (78, 28)
    assert seed_catalog(db, load_catalog_fixture()) == (0, 0)


# --- real May 2026 Major fixture ----------------------------------------------------------


def test_real_fixture_ingests_completely_and_merges_name_variants(seeded: Session):
    for p in load_pages("blast-2026-may"):
        r = ingest(seeded, p.wikitext, p.revid, page=p.title)
        assert r.quarantined == []
    assert count(seeded, Match) == 50
    assert seeded.scalar(select(func.count()).where(MapPlayed.status == "finished")) == 84
    assert count(seeded, OperatorBan) == 960
    assert count(seeded, Team) == 20  # FURIA/Furia and FaZe Clan/Faze Clan are one team each
    valkyrie_maps = seeded.scalar(
        select(func.count(func.distinct(OperatorBan.map_played_id)))
        .join(Operator)
        .join(MapPlayed)
        .where(Operator.name == "Valkyrie", MapPlayed.status == "finished")
    )
    assert valkyrie_maps == 10  # 9 bans spelled "Valkyrie" + 1 spelled "Valk"


# --- idempotency --------------------------------------------------------------------------


def test_same_revision_twice_is_a_no_op(seeded: Session):
    first = ingest(seeded, match_page(), revid=1)
    again = ingest(seeded, match_page(), revid=1)
    assert first.created == 1
    assert again.already_ingested and again.revision_id == first.revision_id
    assert count(seeded, Match) == 1 and count(seeded, PageRevision) == 1


def test_new_revision_with_same_content_changes_nothing(seeded: Session):
    ingest(seeded, match_page(), revid=1)
    r = ingest(seeded, match_page(), revid=2)
    assert (r.created, r.updated, r.unchanged) == (0, 0, 1)
    match = seeded.scalars(select(Match)).one()
    assert match.first_revision_id != match.last_revision_id
    assert count(seeded, OperatorBan) == 4


def test_time_edit_updates_the_match_instead_of_duplicating_it(seeded: Session):
    ingest(seeded, match_page(), revid=1)
    r = ingest(seeded, match_page(date="2026-11-06 - 12:30 {{Abbr/JST}}"), revid=2)
    assert r.updated == 1 and r.corrections == 0
    (match,) = seeded.scalars(select(Match)).all()
    assert match.scheduled_at == datetime(2026, 11, 6, 3, 30, tzinfo=UTC)


def test_map_finishing_later_is_an_update_not_a_correction(seeded: Session):
    ingest(seeded, match_page(status="", rounds="0"), revid=1)
    r = ingest(seeded, match_page(), revid=2)
    assert (r.updated, r.corrections) == (1, 0)
    assert seeded.scalars(select(MapPlayed)).one().status == "finished"


def test_edit_to_a_finished_map_is_applied_and_audited(seeded: Session):
    ingest(seeded, match_page(t1_bans="Mira|t1ban2=Kaid"), revid=1)
    r = ingest(seeded, match_page(t1_bans="Mira|t1ban2=Azami"), revid=2)
    assert (r.updated, r.corrections) == (1, 1)
    corr = seeded.scalars(select(Correction)).one()
    assert corr.before["t1_bans"] == ["Mira", "Kaid"]
    assert corr.after["t1_bans"] == ["Mira", "Azami"]
    banned = set(seeded.scalars(select(Operator.name).join(OperatorBan)))
    assert "Kaid" not in banned and "Azami" in banned


# --- quarantine and isolation -------------------------------------------------------------


def test_unknown_operator_quarantines_the_whole_match(seeded: Session):
    r = ingest(seeded, match_page(t1_bans="Mira|t1ban2=Kaidd"), revid=1)
    assert r.created == 0
    assert r.quarantined == ["unknown operator 'Kaidd'"]
    assert count(seeded, Match) == 0 and count(seeded, OperatorBan) == 0
    assert seeded.scalars(select(Quarantine)).one().namespace == NS


def test_parse_problems_are_quarantined_but_good_matches_still_load(seeded: Session):
    bad = (
        "{{Match|date=2026-11-06 - 10:00 {{Abbr/CST}}|finished=true"
        "|opponent1={{TeamOpponent|A}}|opponent2={{TeamOpponent|B}}}}"
    )
    r = ingest(seeded, match_page() + bad, revid=1)
    # The CST match still loads (with no time, no maps); its problems are recorded, never guessed.
    assert r.created == 2
    assert any("timezone" in q for q in r.quarantined)


def test_replay_and_live_namespaces_never_share_rows(seeded: Session):
    ingest(seeded, match_page(), revid=1, namespace="replay:test")
    r = ingest(seeded, match_page(), revid=1, namespace="live")
    assert r.created == 1 and not r.already_ingested
    assert sorted(seeded.scalars(select(Match.namespace))) == ["live", "replay:test"]
