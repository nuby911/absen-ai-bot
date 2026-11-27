import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Boolean, Column, MetaData, String, Table, create_engine

from app.config import Settings
from app.database import format_column_default_sql, sync_schema_columns
from app.main import create_app
from app.providers.face_engine import InsightFaceEngine, create_face_engine


def test_format_boolean_default_for_postgresql_and_sqlite() -> None:
    meta = MetaData()
    tbl = Table(
        "sample",
        meta,
        Column("is_active", Boolean, nullable=False, default=True),
        Column("is_impostor", Boolean, nullable=True, default=False),
        Column("note", String(50), nullable=True),
        Column("label", String(50), nullable=False, default="O'Brien"),
    )
    assert format_column_default_sql(tbl.c.is_active, "postgresql") == " DEFAULT TRUE"
    assert format_column_default_sql(tbl.c.is_impostor, "postgresql") == " DEFAULT FALSE"
    assert format_column_default_sql(tbl.c.is_active, "sqlite") == " DEFAULT 1"
    assert format_column_default_sql(tbl.c.is_impostor, "sqlite") == " DEFAULT 0"
    assert format_column_default_sql(tbl.c.note, "postgresql") == ""
    assert format_column_default_sql(tbl.c.label, "postgresql") == " DEFAULT 'O''Brien'"


def test_sync_schema_columns_adds_missing_columns_in_sqlite() -> None:
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, name VARCHAR(255) NOT NULL, "
            "email VARCHAR(255) NOT NULL, password_hash TEXT NOT NULL, role VARCHAR(20) NOT NULL, "
            "nip VARCHAR(50), kiosk_pin_hash TEXT, created_at DATETIME NOT NULL)"
        )
        sync_schema_columns(conn)
        cols = [row[1] for row in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
        assert "is_active" in cols
    engine.dispose()


def test_create_face_engine_passes_insightface_home(tmp_path) -> None:
    cfg = Settings(face_engine_mode="insightface", insightface_home=str(tmp_path / "models"))
    engine = create_face_engine(cfg)
    assert isinstance(engine, InsightFaceEngine)
    assert engine.root_dir == str(tmp_path / "models")


def test_create_face_engine_defaults_root_under_upload_dir(tmp_path) -> None:
    cfg = Settings(
        face_engine_mode="insightface",
        upload_dir=str(tmp_path / "uploads"),
        insightface_home="",
    )
    engine = create_face_engine(cfg)
    assert isinstance(engine, InsightFaceEngine)
    assert engine.root_dir == str(tmp_path / "uploads" / ".insightface")


@pytest.mark.asyncio
async def test_health_ready_endpoint_returns_database_ok(tmp_path) -> None:
    db_path = tmp_path / "ready_test.db"
    cfg = Settings(
        database_url=f"sqlite+aiosqlite:///{db_path}",
        upload_dir=str(tmp_path / "uploads"),
        face_engine_mode="deterministic",
        whatsapp_provider_mode="mock",
        llm_provider_mode="fallback",
    )
    app = create_app(settings=cfg)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            res = await client.get("/health/ready")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "database": "ok"}
