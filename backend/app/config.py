from functools import lru_cache
from typing import Literal

from pydantic import Field, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ConfigError(Exception):
    pass


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    database_url_test: str | None = None

    # mock = labeled fixture data; live = Liquipedia API.
    data_mode: Literal["mock", "live"]

    # Liquipedia API terms: identify the app with contact info, and keep to <= 1 request / 2 s.
    liquipedia_api_url: str = "https://liquipedia.net/rainbowsix/api.php"
    liquipedia_user_agent: str = Field(min_length=10)
    liquipedia_min_interval_seconds: float = Field(default=2.0, ge=2.0)
    poll_interval_seconds: int = Field(default=300, ge=60, le=86_400)

    admin_token: str = Field(min_length=24)

    @field_validator("database_url", "database_url_test")
    @classmethod
    def _postgres_only(cls, v: str | None) -> str | None:
        if v is not None and not v.startswith("postgresql+psycopg://"):
            raise ValueError("must be a postgresql+psycopg:// URL")
        return v

    @field_validator("liquipedia_user_agent")
    @classmethod
    def _has_contact(cls, v: str) -> str:
        if "@" not in v and "http" not in v:
            raise ValueError("must include contact info (email or URL) per Liquipedia API terms")
        return v


def load_settings(**overrides: object) -> Settings:
    """Load settings; raise ConfigError naming each bad field without echoing values."""
    try:
        return Settings(**overrides)  # type: ignore[arg-type]
    except ValidationError as e:
        problems = "\n".join(f"  {'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())
        raise ConfigError(f"Invalid configuration:\n{problems}") from None


@lru_cache
def get_settings() -> Settings:
    return load_settings()
