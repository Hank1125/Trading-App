"""Store parsed Liquipedia revisions in Postgres, idempotently.

One call = one page revision = one transaction (the caller owns `session.begin()`):
- the same (namespace, page, revid) is only processed once;
- each match is upserted on its stable `match_key`; unchanged content is a no-op;
- names are resolved through the catalog; a match with any unknown name is quarantined whole,
  never stored partially;
- if a map that was already finished changes in a later revision, the new data is applied and
  the before/after is appended to `siege_correction`.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.siege.catalog import Catalog, CatalogOperator, name_key, team_key
from app.siege.models import (
    Correction,
    MapInfo,
    MapPlayed,
    Match,
    Operator,
    OperatorBan,
    PageRevision,
    Quarantine,
    Team,
    VetoAction,
)
from app.siege.parser import PARSER_VERSION, MatchRecord, parse_page


@dataclass
class IngestReport:
    revision_id: int
    already_ingested: bool = False
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    corrections: int = 0
    quarantined: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return self.created > 0 or self.updated > 0


def seed_catalog(session: Session, catalog: Catalog) -> tuple[int, int]:
    """Insert catalog operators/maps that aren't stored yet. Returns (operators added, maps added)."""
    have_ops = set(session.scalars(select(Operator.name_key)))
    have_maps = set(session.scalars(select(MapInfo.name_key)))
    new_ops = [o for o in catalog.operators if name_key(o.name) not in have_ops]
    new_maps = [m for m in catalog.maps if name_key(m) not in have_maps]
    session.add_all(Operator(name=o.name, name_key=name_key(o.name), side=o.side) for o in new_ops)
    session.add_all(MapInfo(name=m, name_key=name_key(m)) for m in new_maps)
    session.flush()
    return len(new_ops), len(new_maps)


def load_catalog(session: Session) -> Catalog:
    ops = tuple(
        CatalogOperator(o.name, o.side)  # type: ignore[arg-type]
        for o in session.scalars(select(Operator).order_by(Operator.id))
    )
    maps = tuple(session.scalars(select(MapInfo.name).order_by(MapInfo.id)))
    return Catalog(ops, maps)


def _resolve(rec: MatchRecord, catalog: Catalog) -> tuple[dict[str, Any] | None, list[str]]:
    """Canonical, catalog-resolved content for a match, or the list of unknown names."""
    unknown: list[str] = []

    def op(raw: str) -> str:
        found = catalog.resolve_operator(raw)
        if found is None:
            unknown.append(f"unknown operator {raw!r}")
            return raw
        return found.name

    def mp(raw: str) -> str:
        found = catalog.resolve_map(raw)
        if found is None:
            unknown.append(f"unknown map {raw!r}")
            return raw
        return found

    content = {
        "scheduled_at": rec.scheduled_at.isoformat() if rec.scheduled_at else None,
        "date_precision": rec.date_precision,
        "team1": team_key(rec.team1),
        "team2": team_key(rec.team2),
        "finished": rec.finished,
        "forfeit": rec.forfeit,
        "winner": rec.winner,
        "siegegg_id": rec.siegegg_id,
        "maps": [
            {
                "order": m.order,
                "map": mp(m.map_name),
                "status": m.status,
                "team1_first_side": m.team1_first_side,
                "t1": [
                    m.team1_rounds.atk,
                    m.team1_rounds.defense,
                    m.team1_rounds.ot_atk,
                    m.team1_rounds.ot_def,
                ],
                "t2": [
                    m.team2_rounds.atk,
                    m.team2_rounds.defense,
                    m.team2_rounds.ot_atk,
                    m.team2_rounds.ot_def,
                ],
                "t1_bans": [op(b) for b in m.team1_bans],
                "t2_bans": [op(b) for b in m.team2_bans],
            }
            for m in rec.maps
        ],
        "veto": [{"step": v.step, "team": v.team, "kind": v.kind, "map": mp(v.map_name)} for v in rec.veto],
    }
    return (None, unknown) if unknown else (content, [])


def _hash(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True).encode()).hexdigest()


def _team(session: Session, display: str) -> Team:
    key = team_key(display)
    team = session.scalar(select(Team).where(Team.name_key == key))
    if team is None:
        team = Team(name_key=key, name=display)
        session.add(team)
        session.flush()
    return team


def _children(
    session: Session, match: Match, content: dict[str, Any], op_ids: dict[str, int], map_ids: dict[str, int]
) -> None:
    # Delete old children before inserting new ones, so (match_id, order) uniqueness never trips.
    if match.maps or match.veto:
        match.maps.clear()
        match.veto.clear()
        session.flush()
    match.maps = [
        MapPlayed(
            order=m["order"],
            map_id=map_ids[m["map"]],
            status=m["status"],
            team1_first_side=m["team1_first_side"],
            t1_atk=m["t1"][0], t1_def=m["t1"][1], t1_ot_atk=m["t1"][2], t1_ot_def=m["t1"][3],
            t2_atk=m["t2"][0], t2_def=m["t2"][1], t2_ot_atk=m["t2"][2], t2_ot_def=m["t2"][3],
            bans=[
                OperatorBan(team=team, slot=slot, operator_id=op_ids[name])
                for team, key in ((1, "t1_bans"), (2, "t2_bans"))
                for slot, name in enumerate(m[key], start=1)
            ],
        )
        for m in content["maps"]
    ]  # fmt: skip
    match.veto = [
        VetoAction(step=v["step"], team=v["team"], kind=v["kind"], map_id=map_ids[v["map"]])
        for v in content["veto"]
    ]


def _changed_finished_maps(before: dict[str, Any], after: dict[str, Any]) -> list[tuple[Any, Any]]:
    new_by_order = {m["order"]: m for m in after["maps"]}
    return [
        (old, new_by_order.get(old["order"]))
        for old in before["maps"]
        if old["status"] == "finished" and new_by_order.get(old["order"]) != old
    ]


def ingest_revision(
    session: Session,
    *,
    namespace: str,
    page: str,
    revid: int,
    revision_timestamp: str,
    wikitext: str,
    now: datetime,
) -> IngestReport:
    existing = session.scalar(
        select(PageRevision.id).where(
            PageRevision.namespace == namespace, PageRevision.page == page, PageRevision.revid == revid
        )
    )
    if existing is not None:
        return IngestReport(revision_id=existing, already_ingested=True)

    rev = PageRevision(
        namespace=namespace,
        page=page,
        revid=revid,
        revision_timestamp=revision_timestamp,
        fetched_at=now,
        sha256=hashlib.sha256(wikitext.encode()).hexdigest(),
        wikitext=wikitext,
        parser_version=PARSER_VERSION,
    )
    session.add(rev)
    session.flush()
    report = IngestReport(revision_id=rev.id)

    def quarantine(reason: str, context: str) -> None:
        session.add(
            Quarantine(
                namespace=namespace, revision_id=rev.id, reason=reason, context=context, created_at=now
            )
        )
        report.quarantined.append(reason)

    parsed = parse_page(page, wikitext, namespace)
    for problem in parsed.problems:
        quarantine(problem.reason, problem.context)

    catalog = load_catalog(session)
    op_ids = {name: id_ for name, id_ in session.execute(select(Operator.name, Operator.id))}
    map_ids = {name: id_ for name, id_ in session.execute(select(MapInfo.name, MapInfo.id))}

    for rec in parsed.matches:
        content, unknown = _resolve(rec, catalog)
        ctx = f"{page}: {rec.team1} vs {rec.team2}"
        if content is None:
            quarantine("; ".join(sorted(set(unknown))), ctx)
            continue
        digest = _hash(content)
        match = session.scalar(select(Match).where(Match.match_key == rec.match_key))

        if match is None:
            match = Match(
                namespace=namespace,
                match_key=rec.match_key,
                page=page,
                team1_id=_team(session, rec.team1).id,
                team2_id=_team(session, rec.team2).id,
                first_seen_at=now,
                first_revision_id=rev.id,
            )
            session.add(match)
            report.created += 1
        elif match.content_hash == digest:
            match.last_revision_id = rev.id
            report.unchanged += 1
            continue
        else:
            for before, after in _changed_finished_maps(match.content, content):
                session.add(
                    Correction(
                        match_id=match.id,
                        revision_id=rev.id,
                        detected_at=now,
                        before=before,
                        after=after or {},
                    )
                )
                report.corrections += 1
            report.updated += 1

        match.scheduled_at = rec.scheduled_at
        match.date_precision = rec.date_precision
        match.finished = rec.finished
        match.forfeit = rec.forfeit
        match.winner = rec.winner
        match.siegegg_id = rec.siegegg_id
        match.last_revision_id = rev.id
        match.content_hash = digest
        match.content = content
        _children(session, match, content, op_ids, map_ids)
        session.flush()

    return report
