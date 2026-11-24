from collections.abc import AsyncGenerator
from typing import Any

from fastapi import Request
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


def sync_schema_columns(sync_conn: Any) -> None:
    """Ensure missing columns in existing tables are added automatically."""
    from sqlalchemy import inspect, text

    inspector = inspect(sync_conn)
    dialect = sync_conn.dialect
    dialect_name = dialect.name

    for table_name, table in Base.metadata.tables.items():
        if not inspector.has_table(table_name):
            continue
        existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in existing_cols:
                col_type = column.type.compile(dialect=dialect)
                default_clause = ""
                if column.server_default is not None:
                    default_clause = f" DEFAULT {column.server_default.arg}"
                elif column.default is not None and getattr(column.default, "is_scalar", False):
                    val = column.default.arg
                    if isinstance(val, bool):
                        val_str = "1" if val else "0" if dialect_name == "sqlite" else ("TRUE" if val else "FALSE")
                    elif isinstance(val, (int, float)):
                        val_str = str(val)
                    else:
                        val_str = f"'{val}'"
                    default_clause = f" DEFAULT {val_str}"
                elif column.name == "is_active":
                    default_clause = " DEFAULT 1" if dialect_name == "sqlite" else " DEFAULT TRUE"
                elif column.name == "is_impostor":
                    default_clause = " DEFAULT 0" if dialect_name == "sqlite" else " DEFAULT FALSE"

                null_clause = ""
                if not column.nullable and default_clause:
                    null_clause = " NOT NULL"
                elif column.nullable and dialect_name != "sqlite":
                    null_clause = " NULL"

                sql = f"ALTER TABLE {table_name} ADD COLUMN {column.name} {col_type}{null_clause}{default_clause}"
                sync_conn.execute(text(sql))


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


def get_default_engine() -> AsyncEngine:
    """Lazily initialize and return the default async SQLAlchemy engine."""
    get_default_session_factory()
    if _default_engine is None:
        raise RuntimeError("Default async database engine gagal diinisialisasi.")
    return _default_engine


def get_default_session_factory() -> async_sessionmaker[AsyncSession]:
    """Lazily initialize and return the default async session factory."""
    global _default_engine, _default_session_factory
    if _default_session_factory is None:
        settings = get_settings()
        _default_engine, _default_session_factory = create_engine_and_session(
            settings.database_url
        )
    return _default_session_factory


async def dispose_default_engine() -> None:
    """Dispose and reset the cached default async engine on application shutdown."""
    global _default_engine, _default_session_factory
    if _default_engine is not None:
        await _default_engine.dispose()
        _default_engine = None
        _default_session_factory = None


async def get_db(request: Request) -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an async database session bound to app.state."""
    session_factory = getattr(request.app.state, "session_factory", None)
    if session_factory is None:
        settings = getattr(request.app.state, "settings", None)
        if settings is not None:
            engine, session_factory = create_engine_and_session(settings.database_url)
            request.app.state.engine = engine
            request.app.state.session_factory = session_factory
        else:
            session_factory = get_default_session_factory()
    async with session_factory() as session:
        yield session
