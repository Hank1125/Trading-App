"""Insert the operator/map catalog (from the saved Liquipedia portal fixture). Safe to re-run."""

from sqlalchemy.orm import sessionmaker

from app.db import get_engine
from app.siege.fixtures import load_catalog_fixture
from app.siege.ingest import seed_catalog

if __name__ == "__main__":
    with sessionmaker(get_engine())() as session, session.begin():
        ops, maps = seed_catalog(session, load_catalog_fixture())
    print(f"catalog seeded: {ops} operators and {maps} maps added")
