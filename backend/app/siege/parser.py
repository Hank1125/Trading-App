"""Turn Liquipedia Rainbow Six match wikitext into typed, validated records (pure, no I/O).

Problems are collected rather than raised, so one malformed match never hides the rest of a page.
Catalog checks (unknown operator/map names) happen at ingest, not here.
"""

import hashlib
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal

from app.siege.catalog import team_key
from app.siege.wikitext import Template, clean, find_templates, first_template

PARSER_VERSION = "liquipedia-r6-match-v1"

Side = Literal["atk", "def"]
MapStatus = Literal["finished", "skipped", "unplayed"]
VetoKind = Literal["ban", "pick", "decider"]

# Only unambiguous abbreviations; anything else is reported, never guessed (e.g. CST, IST).
TZ_OFFSETS_HOURS: dict[str, float] = {
    "UTC": 0, "GMT": 0, "BST": 1, "WET": 0, "WEST": 1, "CET": 1, "CEST": 2, "EET": 2, "EEST": 3,
    "MSK": 3, "EST": -5, "EDT": -4, "CDT": -5, "MST": -7, "MDT": -6, "PST": -8, "PDT": -7,
    "BRT": -3, "SGT": 8, "KST": 9, "JST": 9, "AEST": 10, "AEDT": 11,
}  # fmt: skip

FORFEIT_SCORES = {"FF", "DQ"}

_DATE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})(?:\s*-?\s*(\d{1,2}):(\d{2})\s*(?:\{\{\s*Abbr/([A-Za-z]+)\s*\}\})?)?\s*$"
)


@dataclass(frozen=True)
class Problem:
    reason: str
    context: str


@dataclass(frozen=True)
class SideRounds:
    atk: int
    defense: int
    ot_atk: int
    ot_def: int

    @property
    def total(self) -> int:
        return self.atk + self.defense + self.ot_atk + self.ot_def


@dataclass(frozen=True)
class MapResult:
    order: int
    map_name: str
    status: MapStatus
    team1_first_side: Side | None
    team1_rounds: SideRounds
    team2_rounds: SideRounds
    team1_bans: tuple[str, ...]
    team2_bans: tuple[str, ...]

    @property
    def winner(self) -> Literal[1, 2] | None:
        a, b = self.team1_rounds.total, self.team2_rounds.total
        if self.status != "finished" or a == b:
            return None
        return 1 if a > b else 2

    @property
    def banned_operators(self) -> frozenset[str]:
        """Operators banned by either team on this map (an op banned by both counts once)."""
        return frozenset(self.team1_bans) | frozenset(self.team2_bans)


@dataclass(frozen=True)
class VetoAction:
    step: int
    team: Literal[1, 2] | None  # None for the decider
    kind: VetoKind
    map_name: str


@dataclass(frozen=True)
class MatchRecord:
    page: str
    match_key: str
    scheduled_at: datetime | None  # UTC
    date_precision: Literal["minute", "day"] | None
    team1: str
    team2: str
    finished: bool
    forfeit: bool
    winner: Literal[1, 2] | None
    maps: tuple[MapResult, ...]
    veto: tuple[VetoAction, ...]
    siegegg_id: str | None = None
    r6esports_id: str | None = None

    @property
    def finished_maps(self) -> tuple[MapResult, ...]:
        return tuple(m for m in self.maps if m.status == "finished")


@dataclass
class ParseResult:
    matches: list[MatchRecord] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)


def match_key(namespace: str, page: str, team1: str, team2: str, occurrence: int) -> str:
    """Stable identity: page + both teams (team_key) + which meeting of that pair on the page.

    Deliberately excludes the date, which editors often adjust, so a time edit never creates a
    second copy of the same match. `occurrence` separates real rematches (e.g. GSL deciders).
    """
    raw = "|".join([namespace, page, team_key(team1), team_key(team2), str(occurrence)])
    return hashlib.sha256(raw.encode()).hexdigest()


def parse_date(value: str) -> tuple[datetime | None, Literal["minute", "day"] | None, str | None]:
    """Return (UTC datetime, precision, problem). Date-only values become 00:00 UTC, precision 'day'."""
    m = _DATE.match(value.strip())
    if not m:
        return None, None, f"unparseable date {value!r}" if value.strip() else "missing date"
    y, mo, d, hh, mm, tz = m.groups()
    if hh is None:
        return datetime(int(y), int(mo), int(d), tzinfo=UTC), "day", None
    if tz is None:
        return None, None, f"time without timezone {value!r}"
    offset = TZ_OFFSETS_HOURS.get(tz.upper())
    if offset is None:
        return None, None, f"unknown timezone {tz!r}"
    local = datetime(int(y), int(mo), int(d), int(hh), int(mm), tzinfo=timezone(timedelta(hours=offset)))
    return local.astimezone(UTC), "minute", None


def _int(value: str, field_name: str, problems: list[Problem], ctx: str) -> int:
    v = value.strip()
    if v == "":
        return 0
    if not v.isdigit():
        problems.append(Problem(f"non-numeric {field_name}={v!r}", ctx))
        return 0
    return int(v)


def _rounds(t: Template, team: int, problems: list[Problem], ctx: str) -> SideRounds:
    def get(key: str) -> int:
        return _int(t.get(f"t{team}{key}"), f"t{team}{key}", problems, ctx)

    return SideRounds(atk=get("atk"), defense=get("def"), ot_atk=get("otatk"), ot_def=get("otdef"))


def _bans(t: Template, team: int) -> tuple[str, ...]:
    slots = sorted(
        (int(k[len(f"t{team}ban") :]), v.strip())
        for k, v in t.params.items()
        if re.fullmatch(rf"t{team}ban\d+", k)
    )
    return tuple(v for _, v in slots if v)


def _parse_map(t: Template, order: int, problems: list[Problem], ctx: str) -> MapResult | None:
    name = t.get("map").strip()
    raw_status = t.get("finished").strip().lower()
    status: MapStatus = {"true": "finished", "skip": "skipped"}.get(raw_status, "unplayed")  # type: ignore[assignment]
    if not name:
        if status == "finished":
            problems.append(Problem("finished map without a name", ctx))
        return None
    first = t.get("t1firstside").strip().lower()
    t1 = _rounds(t, 1, problems, ctx)
    t2 = _rounds(t, 2, problems, ctx)
    result = MapResult(
        order=order,
        map_name=name,
        status=status,
        team1_first_side=first if first in ("atk", "def") else None,  # type: ignore[arg-type]
        team1_rounds=t1,
        team2_rounds=t2,
        team1_bans=_bans(t, 1),
        team2_bans=_bans(t, 2),
    )
    if status == "finished" and result.winner is None:
        problems.append(Problem(f"finished map {name!r} has no winner ({t1.total}-{t2.total})", ctx))
    return result


def _parse_veto(t: Template | None) -> tuple[VetoAction, ...]:
    if t is None:
        return ()
    kinds = [k.strip().lower() for k in t.get("types").split(",") if k.strip()]
    actions: list[VetoAction] = []
    step = 0
    for i, kind in enumerate(kinds, start=1):
        if kind == "decider":
            if name := t.get("decider").strip():
                step += 1
                actions.append(VetoAction(step, None, "decider", name))
            continue
        if kind not in ("ban", "pick"):
            continue
        for team in (1, 2):
            if name := t.get(f"t{team}map{i}").strip():
                step += 1
                actions.append(VetoAction(step, team, kind, name))  # type: ignore[arg-type]
    return tuple(actions)


def _opponent(value: str) -> tuple[str, str]:
    t = first_template(value, "TeamOpponent")
    if t is None or not t.positional:
        return "", ""
    return t.positional[0], t.get("score").strip().upper()


def _parse_match(
    t: Template, page: str, namespace: str, problems: list[Problem], meetings: Counter[tuple[str, str]]
) -> MatchRecord | None:
    team1, score1 = _opponent(t.get("opponent1"))
    team2, score2 = _opponent(t.get("opponent2"))
    ctx = f"{page}: {team1 or '?'} vs {team2 or '?'} ({t.get('date') or 'no date'})"
    if not team1 or not team2:
        if t.get("finished").strip() == "true":
            problems.append(Problem("finished match missing an opponent", ctx))
        return None  # unscheduled bracket slots (TBD) are normal, not problems
    if team_key(team1) == team_key(team2):
        problems.append(Problem("same team on both sides", ctx))
        return None

    pair = (team_key(team1), team_key(team2))
    meetings[pair] += 1

    scheduled, precision, date_problem = parse_date(t.get("date"))
    if date_problem:
        problems.append(Problem(date_problem, ctx))

    finished = t.get("finished").strip().lower() == "true"
    forfeit = score1 in FORFEIT_SCORES or score2 in FORFEIT_SCORES

    maps: list[MapResult] = []
    for i in range(1, 20):
        raw = t.get(f"map{i}")
        if not raw:
            continue
        mt = first_template(raw, "Map")
        if mt is not None and (m := _parse_map(mt, i, problems, ctx)) is not None:
            maps.append(m)

    winner: Literal[1, 2] | None = None
    if forfeit:
        winner = 2 if score1 in FORFEIT_SCORES else 1
        if any(m.status == "finished" for m in maps):
            problems.append(Problem("forfeit match also has finished maps", ctx))
    elif finished:
        w1 = sum(1 for m in maps if m.winner == 1)
        w2 = sum(1 for m in maps if m.winner == 2)
        winner = 1 if w1 > w2 else 2 if w2 > w1 else None
        if winner is None:
            problems.append(Problem(f"finished match without a winner ({w1}-{w2} maps)", ctx))

    return MatchRecord(
        page=page,
        match_key=match_key(namespace, page, team1, team2, meetings[pair]),
        scheduled_at=scheduled,
        date_precision=precision,
        team1=team1,
        team2=team2,
        finished=finished,
        forfeit=forfeit,
        winner=winner,
        maps=tuple(maps),
        veto=_parse_veto(first_template(t.get("mapveto"), "MapVeto")),
        siegegg_id=t.get("siegegg").strip() or None,
        r6esports_id=t.get("r6esports").strip() or None,
    )


def parse_page(page: str, wikitext: str, namespace: str) -> ParseResult:
    result = ParseResult()
    meetings: Counter[tuple[str, str]] = Counter()
    for t in find_templates(clean(wikitext), "Match"):
        record = _parse_match(t, page, namespace, result.problems, meetings)
        if record is not None:
            result.matches.append(record)
    return result
