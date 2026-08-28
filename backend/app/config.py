"""Application configuration, sourced from environment variables (.env supported)."""
import os
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_INSECURE_TOKEN = "changeme"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_prefix="FLAKERADAR_", extra="ignore"
    )

    # Auth token CI systems must send in the X-API-Key header when ingesting.
    api_token: str = DEFAULT_INSECURE_TOKEN

    database_url: str = "sqlite:///./data/flakeradar.db"

    # Scoring parameters. window: how many recent executions to consider.
    # decay: geometric weight applied per step into the past (recent flips matter more).
    score_window: int = 50
    score_decay: float = 0.85

    # GitHub integration. Leave token/repo empty to disable (graceful no-op).
    github_token: str = ""
    github_repo: str = ""  # "owner/name"
    flake_threshold: float = 0.30

    cors_origins: str = "http://localhost:5173"


@lru_cache
def get_settings() -> Settings:
    return Settings()


def assert_secure_token(token: str) -> None:
    """Refuse to boot on the shipped default token unless explicitly allowed.

    Tests and throwaway local demos set ``FLAKERADAR_ALLOW_INSECURE=1``.
    Docker/production must set a real ``FLAKERADAR_API_TOKEN``.
    """
    if token != DEFAULT_INSECURE_TOKEN:
        return
    if os.getenv("FLAKERADAR_ALLOW_INSECURE", "").strip() == "1":
        return
    raise RuntimeError(
        "FLAKERADAR_API_TOKEN is still the default 'changeme'. Set a real "
        "token (see .env.example) or set FLAKERADAR_ALLOW_INSECURE=1 for a "
        "throwaway local demo."
    )
