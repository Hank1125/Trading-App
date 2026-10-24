"""Access to saved Liquipedia wikitext fixtures (see scripts/fetch_fixture.py)."""

import json
from dataclasses import dataclass
from pathlib import Path

from app.siege.catalog import Catalog, parse_map_portal, parse_operator_portal

FIXTURES_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "siege"


@dataclass(frozen=True)
class FixturePage:
    title: str
    revid: int
    revision_timestamp: str
    wikitext: str


def load_pages(slug: str) -> list[FixturePage]:
    folder = FIXTURES_DIR / slug
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    return [
        FixturePage(
            p["title"], p["revid"], p["revisionTimestamp"], (folder / p["file"]).read_text(encoding="utf-8")
        )
        for p in meta["pages"]
    ]


def load_catalog_fixture() -> Catalog:
    pages = {p.title: p.wikitext for p in load_pages("catalog")}
    return Catalog(parse_operator_portal(pages["Portal:Operators"]), parse_map_portal(pages["Portal:Maps"]))
