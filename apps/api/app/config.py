"""Application configuration.

Settings are read from the environment (prefix `INCIDENTIQ_`) with local-development
defaults, so a clean checkout runs without any env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

Environment = Literal["local", "test", "production"]

# apps/api/app/config.py -> apps/api -> apps -> repository root
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INCIDENTIQ_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    service_name: str = "incidentiq-api"
    environment: Environment = "local"

    # The Next.js dev server. CORS is opened for local development only; a deployed
    # environment must set this explicitly rather than inherit the default.
    cors_allow_origins: tuple[str, ...] = ("http://localhost:3000",)

    # Synthetic development fixtures. There is no database yet; this directory is the
    # only source of records the API serves.
    fixtures_dir: Path = REPO_ROOT / "data" / "demo" / "northstar_cloud"


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, safe to use as a FastAPI dependency."""
    return Settings()
