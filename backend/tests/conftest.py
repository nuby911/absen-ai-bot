from collections.abc import AsyncGenerator

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.database import Base, create_engine_and_session


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated in-memory async SQLite session with foreign keys enabled."""
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()
