from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import StaticPool

from app.config import get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_engine_and_session(
    database_url: str,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """Create an async SQLAlchemy engine and session factory for SQLite or PostgreSQL."""
    if database_url.startswith("sqlite"):
        engine_kwargs: dict[str, Any] = {"echo": False}
        if ":memory:" in database_url:
            engine_kwargs["poolclass"] = StaticPool
            engine_kwargs["connect_args"] = {"check_same_thread": False}
        engine = create_async_engine(database_url, **engine_kwargs)
        event.listen(engine.sync_engine, "connect", _enable_sqlite_foreign_keys)
    else:
        engine = create_async_engine(database_url, echo=False, pool_pre_ping=True)

    session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    return engine, session_factory


_default_engine: AsyncEngine | None = None
_default_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_default_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily initialize and return the default async session factory."""
    global _default_engine, _default_session_factory
    if _default_session_factory is None:
        settings = get_settings()
        _default_engine, _default_session_factory = create_engine_and_session(
            settings.database_url
        )
    return _default_session_factory


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session."""
    session_factory = get_default_session_factory()
    async with session_factory() as session:
        yield session
