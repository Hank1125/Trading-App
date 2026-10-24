import hashlib
import json
from pathlib import Path

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "siege" / "blast-2026-may"


def test_replay_fixture_matches_recorded_checksums_and_credits_liquipedia():
    meta = json.loads((FIXTURE / "meta.json").read_text())
    assert "CC-BY-SA" in meta["license"] and "Liquipedia" in meta["license"]
    assert len(meta["pages"]) == 2
    for p in meta["pages"]:
        text = (FIXTURE / p["file"]).read_text(encoding="utf-8")
        assert hashlib.sha256(text.encode()).hexdigest() == p["sha256"], p["file"]
