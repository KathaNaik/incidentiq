"""Engine and session lifecycle.

Thin on purpose. SQLAlchemy already is the persistence abstraction; wrapping it in
another one would add a layer whose only job is to be a layer.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings


class DatabaseNotConfiguredError(RuntimeError):
    """No DATABASE_URL is set.

    Raised rather than defaulted. A silent fallback to some local database would make a
    misconfigured deployment look like an empty one, and "your investigations vanished"
    is a much worse failure than "the database is not configured".
    """


@lru_cache
def get_engine() -> Engine:
    """The process-wide engine.

    `pool_pre_ping` because a developer's database is routinely stopped and restarted
    under a running API, and a stale pooled connection surfaces as a confusing error at
    the next request rather than at the moment the container went away.
    """
    url = get_settings().database_url
    if not url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Start PostgreSQL with `docker compose up -d` and "
            "copy apps/api/.env.example to apps/api/.env."
        )
    return create_engine(url, pool_pre_ping=True, future=True)


def sessionmaker_for(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    """A transaction. Commits on success, rolls back on anything raised."""
    factory = sessionmaker_for(engine or get_engine())
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def dispose_engine() -> None:
    """Drops pooled connections. Used by tests that rebuild the schema."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
