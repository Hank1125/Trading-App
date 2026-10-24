"""One-time download of an event's Liquipedia wikitext for the replay demo.

Usage: python -m scripts.fetch_fixture <slug> <page title>...
  e.g. blast-2026-may "BLAST Major/2026/May" "BLAST Major/2026/May/Phase 2"
       catalog "Portal:Operators" "Portal:Maps"
"""

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

from app.siege.liquipedia import client_from_settings

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "siege"


def main(slug: str, titles: list[str]) -> None:
    out_dir = FIXTURES / slug
    out_dir.mkdir(parents=True, exist_ok=True)
    client = client_from_settings()
    pages = []
    try:
        for title in titles:
            page = client.get_page(title)
            filename = re.sub(r"[^A-Za-z0-9._-]", "_", title.replace("/", "__")) + ".wikitext"
            (out_dir / filename).write_text(page.wikitext, encoding="utf-8")
            pages.append(
                {
                    "title": page.title,
                    "file": filename,
                    "revid": page.revid,
                    "revisionTimestamp": page.timestamp,
                    "sha256": hashlib.sha256(page.wikitext.encode()).hexdigest(),
                    "source": f"https://liquipedia.net/rainbowsix/{page.title.replace(' ', '_')}",
                }
            )
            print(f"saved {title} (rev {page.revid}, {len(page.wikitext)} chars)")
    finally:
        client.close()
    meta = {
        "slug": slug,
        "fetchedAt": datetime.now(UTC).isoformat(timespec="seconds"),
        "license": "CC-BY-SA 3.0 — content from Liquipedia (https://liquipedia.net/rainbowsix), unmodified.",
        "pages": pages,
    }
    (out_dir / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2:])
