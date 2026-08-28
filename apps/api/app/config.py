"""Application configuration.

Settings are read from the environment (prefix `INCIDENTIQ_`) with local-development
defaults, so a clean checkout runs without any env file.
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field
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

    # Committed evaluation artifacts produced by the offline harness. The API reads
    # them; it never runs an evaluation itself.
    evals_dir: Path = REPO_ROOT / "data" / "evals" / "triage"
    correlation_evals_dir: Path = REPO_ROOT / "data" / "evals" / "correlation"

    # Embedding vectors, cached so repeated evaluations reuse identical numbers.
    # Gitignored: derived from ticket text, including licensed corpora.
    embeddings_cache_dir: Path = REPO_ROOT / "data" / "processed" / "embeddings"

    # Historical corpus. Northstar records are committed; the external corpus appears
    # only after the ingestion scripts run, and retrieval works without it.
    itsm_processed_dir: Path = REPO_ROOT / "data" / "processed" / "itsm"
    retrieval_evals_dir: Path = REPO_ROOT / "data" / "evals" / "retrieval"
    investigation_evals_dir: Path = REPO_ROOT / "data" / "evals" / "investigation"

    # Model used for investigation.
    investigation_model: str = "gpt-5.6-terra"

    # Read from the plain OPENAI_API_KEY name rather than the INCIDENTIQ_ prefix, since
    # that is the variable the OpenAI tooling ecosystem already uses. Picked up from the
    # environment or from a gitignored .env; never committed, never logged.
    openai_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor, safe to use as a FastAPI dependency."""
    return Settings()
