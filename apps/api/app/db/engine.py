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


def normalize_database_url(url: str) -> str:
    """Makes a provider's connection string say which driver to use.

    Managed Postgres providers hand out `postgres://` or `postgresql://` URLs. SQLAlchemy
    reads a bare `postgresql://` as "use psycopg2", which this project does not install —
    it uses psycopg 3. Without this, a perfectly valid `DATABASE_URL` copied from a
    provider's dashboard fails at import with `No module named 'psycopg2'`, which says
    nothing about the actual problem.

    Rewriting here rather than asking every operator to hand-edit the URL means the value
    the platform injects works unmodified. An explicit driver is left alone.
    """
    for prefix in ("postgresql+", "postgres+"):
        if url.startswith(prefix):
            return url
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache
def get_engine() -> Engine:
    """The process-wide engine.

    `pool_pre_ping` because a developer's database is routinely stopped and restarted
    under a running API, and a stale pooled connection surfaces as a confusing error at
    the next request rather than at the moment the container went away. The same setting
    earns its keep in production for a different reason: a serverless instance can sit
    idle long enough for the provider to close its connections underneath it.

    The pool is deliberately small. Vercel scales instances horizontally, so the
    connection count is *pool size × live instances*, and a generous per-instance pool is
    how a serverless deployment exhausts a managed database's connection limit. A handful
    of connections per instance is plenty for a request that spends most of its time
    waiting on OpenAI rather than on Postgres.
    """
    settings = get_settings()
    url = settings.database_url
    if not url:
        raise DatabaseNotConfiguredError(
            "DATABASE_URL is not set. Start PostgreSQL with `docker compose up -d` and "
            "copy apps/api/.env.example to apps/api/.env."
        )
    return create_engine(
        normalize_database_url(url),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        # Recycled well inside the provider's idle timeout, so a connection is replaced
        # on our schedule rather than discovered dead on someone's request.
        pool_recycle=settings.db_pool_recycle_seconds,
        future=True,
    )


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
