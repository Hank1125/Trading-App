"""Load a saved event into its replay namespace *as it happened*, map by map.

Each finished map is revealed at its historical time (match start + 45 min per map), by ingesting a
sequence of page versions where later maps are still unfinished. Stats "as of T" then replay the
event exactly: a demo clock moving through the event's dates sees maps land one by one, through the
same parser/ingest code as live data.

Usage: python -m scripts.ingest_replay_history blast-2026-may
Wipes only the `replay:<slug>` namespace first (never `live`).
"""

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db import get_engine
from app.siege.fixtures import load_pages
from app.siege.ingest import ingest_revision
from app.siege.models import (
    Correction,
    MapObservation,
    MapPlayed,
    Match,
    OperatorBan,
    PageRevision,
    Quarantine,
    VetoAction,
)
from app.siege.parser import parse_date
from app.siege.wikitext import clean, find_templates

MINUTES_PER_MAP = 45


def wipe_namespace(session: Session, namespace: str) -> None:
    if not namespace.startswith("replay:"):
        raise SystemExit("refusing to wipe a non-replay namespace")
    match_ids = select(Match.id).where(Match.namespace == namespace)
    map_ids = select(MapPlayed.id).where(MapPlayed.match_id.in_(match_ids))
    session.execute(delete(OperatorBan).where(OperatorBan.map_played_id.in_(map_ids)))
    for model in (MapPlayed, VetoAction, MapObservation, Correction):
        session.execute(delete(model).where(model.match_id.in_(match_ids)))
    session.execute(delete(Match).where(Match.namespace == namespace))
    session.execute(delete(Quarantine).where(Quarantine.namespace == namespace))
    session.execute(delete(PageRevision).where(PageRevision.namespace == namespace))


Plan = list[tuple[int, int, list[tuple[int, int, datetime]]]]


def reveal_plan(text: str) -> Plan:
    """For each Match: (start, end, [(map_start, map_end, reveal_time)]) in cleaned-text offsets."""
    plan = []
    for m in find_templates(text, "Match"):
        end = m.offset + _span(text, m.offset)
        scheduled, precision, _ = parse_date(m.get("date"))
        maps = []
        if scheduled is not None and precision == "minute":
            src = text[m.offset : end]
            for order, mt in enumerate(find_templates(src, "Map"), start=1):
                if mt.get("finished").strip() == "true":
                    reveal = scheduled + timedelta(minutes=MINUTES_PER_MAP * order)
                    maps.append((m.offset + mt.offset, m.offset + mt.offset + _span(src, mt.offset), reveal))
        plan.append((m.offset, end, maps))
    return plan


def _span(text: str, start: int) -> int:
    depth, i = 0, start
    while i < len(text) - 1:
        pair = text[i : i + 2]
        if pair == "{{":
            depth, i = depth + 1, i + 2
        elif pair == "}}":
            depth, i = depth - 1, i + 2
            if depth == 0:
                return i - start
        else:
            i += 1
    raise ValueError("unbalanced template")


def version_at(text: str, plan: Plan, t: datetime) -> str:
    """The page as it looked at time t: maps not yet revealed are marked unfinished."""
    cuts = sorted((a, b) for _, _, maps in plan for a, b, reveal in maps if reveal > t)
    out, pos = [], 0
    for a, b in cuts:
        out.append(text[pos:a])
        out.append(text[a:b].replace("finished=true", "finished=", 1))
        pos = b
    out.append(text[pos:])
    return "".join(out)


def main(slug: str) -> None:
    namespace = f"replay:{slug}"
    factory = sessionmaker(get_engine())
    with factory() as session, session.begin():
        wipe_namespace(session, namespace)
    pages = [(p, clean(p.wikitext)) for p in load_pages(slug)]
    plans = {p.title: reveal_plan(text) for p, text in pages}
    times = sorted({r for plan in plans.values() for _, _, maps in plan for _, _, r in maps})
    first = times[0] - timedelta(minutes=1) if times else datetime.now(UTC)
    steps = [first, *times]
    for step, t in enumerate(steps):
        for page, text in pages:
            with factory() as session, session.begin():
                ingest_revision(
                    session,
                    namespace=namespace,
                    page=page.title,
                    revid=page.revid * 1000 + step,
                    revision_timestamp=t.isoformat(),
                    wikitext=version_at(text, plans[page.title], t),
                    now=t,
                )
    span = f"{times[0]:%Y-%m-%d %H:%M} to {times[-1]:%Y-%m-%d %H:%M} UTC"
    print(f"{namespace}: {len(times)} map reveals from {span}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
