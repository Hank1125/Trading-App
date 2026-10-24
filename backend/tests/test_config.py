import pytest

from app.config import ConfigError, load_settings

VALID = dict(
    database_url="postgresql+psycopg://u@localhost:5433/db",
    data_mode="live",
    liquipedia_user_agent="TestApp/0.1 (https://example.com)",
    admin_token="x" * 32,
)


def load(**over):
    return load_settings(_env_file=None, **{**VALID, **over})


def test_valid_config_loads_with_safe_defaults():
    s = load()
    assert s.data_mode == "live"
    assert s.liquipedia_min_interval_seconds == 2.0


def test_rejects_unknown_data_mode():
    with pytest.raises(ConfigError, match="data_mode"):
        load(data_mode="scrape")


def test_rejects_non_postgres_url():
    with pytest.raises(ConfigError, match="database_url"):
        load(database_url="sqlite:///dev.db")


def test_refuses_to_poll_liquipedia_faster_than_terms_allow():
    with pytest.raises(ConfigError, match="liquipedia_min_interval_seconds"):
        load(liquipedia_min_interval_seconds=1.0)


def test_user_agent_must_carry_contact_info():
    with pytest.raises(ConfigError, match="liquipedia_user_agent"):
        load(liquipedia_user_agent="python-requests/2.0")


def test_error_never_echoes_secret_values():
    with pytest.raises(ConfigError) as exc:
        load(admin_token="secret123")
    assert "admin_token" in str(exc.value)
    assert "secret123" not in str(exc.value)
