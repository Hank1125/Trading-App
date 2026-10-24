import hashlib
import json

import pytest

from app.siege.fixtures import FIXTURES_DIR

FIXTURE_DIRS = sorted(p for p in FIXTURES_DIR.iterdir() if (p / "meta.json").exists())


def test_expected_fixtures_exist():
    assert {p.name for p in FIXTURE_DIRS} >= {"blast-2026-may", "catalog"}


@pytest.mark.parametrize("folder", FIXTURE_DIRS, ids=lambda p: p.name)
def test_fixture_matches_recorded_checksums_and_credits_liquipedia(folder):
    meta = json.loads((folder / "meta.json").read_text())
    assert "CC-BY-SA" in meta["license"] and "Liquipedia" in meta["license"]
    assert meta["pages"]
    for p in meta["pages"]:
        text = (folder / p["file"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode()).hexdigest() == p["sha256"], p["file"]
