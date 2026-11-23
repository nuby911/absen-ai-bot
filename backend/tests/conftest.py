from collections.abc import AsyncGenerator

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.models  # noqa: F401
from app.config import Settings, get_settings
from app.database import Base, create_engine_and_session, get_db
from app.main import create_app
from app.models import User
from app.security import create_access_token, hash_secret


@pytest.fixture
def test_settings() -> Settings:
    """Provide isolated test settings without mutating the cached get_settings()."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        jwt_secret="test-jwt-secret-key-for-smart-school-2026",
        whatsapp_provider_mode="mock",
        llm_provider_mode="fallback",
    )


@pytest.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an isolated in-memory async SQLite session with foreign keys enabled."""
    engine, session_factory = create_engine_and_session("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def client(
    db_session: AsyncSession,
    test_settings: Settings,
) -> AsyncGenerator[httpx.AsyncClient, None]:
    """Provide an async HTTP test client wired to the isolated DB and test settings."""
    app = create_app(settings=test_settings)

    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_settings] = lambda: test_settings

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client

    app.dependency_overrides.clear()


@pytest.fixture
async def seeded_admin(db_session: AsyncSession) -> User:
    """Seed and return an admin user in the test database."""
    admin = User(
        name="Admin Sekolah",
        email="admin@sekolah.sch.id",
        password_hash=hash_secret("admin123"),
        role="admin",
        nip="198001012010011001",
    )
    db_session.add(admin)
    await db_session.commit()
    await db_session.refresh(admin)
    return admin


@pytest.fixture
async def seeded_teacher(db_session: AsyncSession) -> User:
    """Seed and return a teacher user in the test database."""
    teacher = User(
        name="Budi Santoso",
        email="budi@sekolah.sch.id",
        password_hash=hash_secret("guru123"),
        role="teacher",
        nip="198805152014021002",
    )
    db_session.add(teacher)
    await db_session.commit()
    await db_session.refresh(teacher)
    return teacher


@pytest.fixture
def admin_headers(seeded_admin: User, test_settings: Settings) -> dict[str, str]:
    """Return Bearer authorization headers for the seeded admin user."""
    token = create_access_token(
        seeded_admin.id,
        seeded_admin.role,
        settings=test_settings,
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def teacher_headers(seeded_teacher: User, test_settings: Settings) -> dict[str, str]:
    """Return Bearer authorization headers for the seeded teacher user."""
    token = create_access_token(
        seeded_teacher.id,
        seeded_teacher.role,
        settings=test_settings,
    )
    return {"Authorization": f"Bearer {token}"}
