import pytest
from fastapi.testclient import TestClient

from app import db, main
from app.config import get_settings


@pytest.fixture
def client(monkeypatch):
    test_url = get_settings().database_url_test
    if not test_url:
        pytest.skip("DATABASE_URL_TEST not set")
    monkeypatch.setattr(main, "get_engine", lambda: db.make_engine(test_url))
    return TestClient(main.app)


def test_health_reports_reachable_database(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "dataMode": get_settings().data_mode, "database": "reachable"}


def test_health_reports_unreachable_database_without_leaking_url(monkeypatch):
    bad = "postgresql+psycopg://nobody:hunter2@localhost:1/none"
    monkeypatch.setattr(main, "get_engine", lambda: db.make_engine(bad))
    r = TestClient(main.app).get("/api/health")
    assert r.status_code == 503
    assert r.json()["ok"] is False
    assert "hunter2" not in r.text
