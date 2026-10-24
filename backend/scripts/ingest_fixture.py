"""Ingest every page of a saved event fixture into its replay namespace (all at once, no demo clock).

Usage: python -m scripts.ingest_fixture blast-2026-may
"""

import sys
from datetime import UTC, datetime

from sqlalchemy.orm import sessionmaker

from app.db import get_engine
from app.siege.fixtures import load_pages
from app.siege.ingest import ingest_revision

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    slug = sys.argv[1]
    factory = sessionmaker(get_engine())
    for page in load_pages(slug):
        with factory() as session, session.begin():
            r = ingest_revision(
                session,
                namespace=f"replay:{slug}",
                page=page.title,
                revid=page.revid,
                revision_timestamp=page.revision_timestamp,
                wikitext=page.wikitext,
                now=datetime.now(UTC),
            )
        status = (
            "already ingested"
            if r.already_ingested
            else (
                f"created {r.created}, updated {r.updated}, unchanged {r.unchanged}, "
                f"corrections {r.corrections}, quarantined {len(r.quarantined)}"
            )
        )
        print(f"{page.title} (rev {page.revid}): {status}")
