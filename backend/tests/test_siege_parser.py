import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.siege.parser import parse_date, parse_page
from app.siege.wikitext import clean, find_templates, parse_template

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "siege" / "blast-2026-may"
NS = "replay:blast-2026-may"


@pytest.fixture(scope="module")
def may_major():
    meta = json.loads((FIXTURE / "meta.json").read_text())
    matches, problems = [], []
    for p in meta["pages"]:
        r = parse_page(p["title"], (FIXTURE / p["file"]).read_text(encoding="utf-8"), NS)
        matches += r.matches
        problems += r.problems
    return matches, problems


# --- real fixture -------------------------------------------------------------------------


def test_fixture_totals_match_the_real_event(may_major):
    matches, problems = may_major
    finished_maps = [m for x in matches for m in x.finished_maps]
    assert problems == []
    assert len(matches) == 50
    assert sum(x.forfeit for x in matches) == 2
    assert len(finished_maps) == 84
    assert sum(len(m.team1_bans) + len(m.team2_bans) for m in finished_maps) == 960


def test_fixture_spot_check_enterprise_vs_edward(may_major):
    matches, _ = may_major
    (m,) = [x for x in matches if (x.team1, x.team2) == ("ENTERPRISE Esports", "EDward Gaming")]
    assert m.scheduled_at == datetime(2026, 5, 8, 16, 30, tzinfo=UTC)  # 10:30 MDT
    assert m.winner == 1 and m.finished and not m.forfeit
    (fortress,) = m.finished_maps
    assert fortress.map_name == "Fortress"
    assert (fortress.team1_rounds.total, fortress.team2_rounds.total) == (7, 2)
    assert fortress.team1_first_side == "atk"
    assert fortress.team1_bans == ("Clash", "Azami", "Solis", "Solid Snake", "Glaz")
    assert fortress.team2_bans == ("Ying", "Glaz", "Deimos", "Bandit", "Kaid")
    assert len(fortress.banned_operators) == 9  # Glaz banned by both teams counts once
    assert [(v.kind, v.map_name) for v in m.veto][-1] == ("decider", "Fortress")
    assert sum(v.kind == "ban" for v in m.veto) == 8


def test_fixture_forfeits_have_no_maps_and_a_winner(may_major):
    matches, _ = may_major
    for m in (x for x in matches if x.forfeit):
        assert "Wolves Esports" in (m.team1, m.team2)
        assert m.finished_maps == ()
        assert m.winner is not None and (m.team1, m.team2)[m.winner - 1] != "Wolves Esports"
        assert m.date_precision == "day"


def test_match_keys_are_unique_and_namespaced(may_major):
    matches, _ = may_major
    keys = {m.match_key for m in matches}
    assert len(keys) == len(matches)
    page, wikitext = _single_match_page()
    assert (
        parse_page(page, wikitext, "live").matches[0].match_key
        != parse_page(page, wikitext, NS).matches[0].match_key
    )


# --- wikitext reader ----------------------------------------------------------------------


def test_split_respects_nested_templates_and_links():
    t = parse_template("{{Match|opponent1={{TeamOpponent|G2|score=W}}|comment=see [[A|B]]|x}}")
    assert t.name == "Match"
    assert t.get("opponent1") == "{{TeamOpponent|G2|score=W}}"
    assert t.get("comment") == "see [[A|B]]"
    assert t.positional == ("x",)


def test_find_templates_is_exact_on_name():
    text = "{{Matchlist|id=x|M1={{Match|finished=true}}}}"
    assert [t.name for t in find_templates(text, "Match")] == ["Match"]


def test_clean_drops_comments_and_refs_with_broken_quotes():
    raw = 'a<!-- {{Match|x}} -->b<ref name="Wolves>{{cite web|url=u}}</ref>c<ref name=x/>d'
    assert clean(raw) == "abcd"


# --- dates --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected,precision",
    [
        ("2026-05-08 - 10:30 {{Abbr/MDT}}", datetime(2026, 5, 8, 16, 30, tzinfo=UTC), "minute"),
        ("2026-10-05 18:00 {{Abbr/CEST}}", datetime(2026, 10, 5, 16, 0, tzinfo=UTC), "minute"),
        ("2026-05-09", datetime(2026, 5, 9, tzinfo=UTC), "day"),
    ],
)
def test_parse_date_formats(value, expected, precision):
    assert parse_date(value) == (expected, precision, None)


@pytest.mark.parametrize("value", ["2026-05-08 - 10:30 {{Abbr/CST}}", "2026-05-08 10:30", "soon", ""])
def test_ambiguous_or_bad_dates_are_reported_not_guessed(value):
    dt, _, problem = parse_date(value)
    assert dt is None and problem


# --- edge cases ---------------------------------------------------------------------------


def _single_match_page(map_block: str = "", opp2: str = "{{TeamOpponent|B}}", date: str = "2026-11-06"):
    default_map = (
        "|map1={{Map|map=Bank|finished=true|t1ban1=Mira|t2ban1=Mira|t2ban2=Kaid"
        "|t1firstside=def|t1atk=3|t1def=4|t1otatk=|t1otdef=|t2atk=2|t2def=3}}"
    )
    return "P", (
        f"{{{{Match|date={date}|finished=true|opponent1={{{{TeamOpponent|A}}}}|opponent2={opp2}"
        f"{map_block or default_map}}}}}"
    )


def test_unplayed_tbd_slots_are_skipped_silently():
    r = parse_page("P", "{{Match|finished=|opponent1={{TeamOpponent|}}|opponent2=}}", NS)
    assert r.matches == [] and r.problems == []


def test_skipped_map_is_not_a_finished_map():
    _, text = _single_match_page()
    text = text.replace("}}}}", "}}|map2={{Map|map=Villa|finished=skip}}}}")
    (m,) = parse_page("P", text, NS).matches
    assert [x.status for x in m.maps] == ["finished", "skipped"]
    assert len(m.finished_maps) == 1


def test_tied_finished_map_is_reported():
    block = "|map1={{Map|map=Bank|finished=true|t1atk=3|t1def=3|t2atk=3|t2def=3}}"
    _, text = _single_match_page(map_block=block)
    r = parse_page("P", text, NS)
    assert any("no winner" in p.reason for p in r.problems)


def test_non_numeric_rounds_are_reported():
    block = "|map1={{Map|map=Bank|finished=true|t1atk=x|t1def=4|t2atk=1|t2def=1}}"
    _, text = _single_match_page(map_block=block)
    assert any("non-numeric" in p.reason for p in parse_page("P", text, NS).problems)


def test_editing_match_time_keeps_the_same_key():
    _, before = _single_match_page(date="2026-11-06 - 10:00 {{Abbr/JST}}")
    _, after = _single_match_page(date="2026-11-06 - 12:30 {{Abbr/JST}}")
    assert parse_page("P", before, NS).matches[0].match_key == parse_page("P", after, NS).matches[0].match_key


def test_team_name_case_does_not_change_the_key():
    _, a = _single_match_page(opp2="{{TeamOpponent|Furia}}")
    _, b = _single_match_page(opp2="{{TeamOpponent|FURIA}}")
    assert parse_page("P", a, NS).matches[0].match_key == parse_page("P", b, NS).matches[0].match_key


def test_rematch_on_the_same_page_gets_its_own_key():
    _, text = _single_match_page()
    first, second = parse_page("P", text + text, NS).matches
    assert first.match_key != second.match_key


def test_same_team_spelled_differently_on_both_sides_is_rejected():
    _, text = _single_match_page(opp2="{{TeamOpponent|a}}")
    r = parse_page("P", text, NS)
    assert r.matches == [] and [p.reason for p in r.problems] == ["same team on both sides"]
