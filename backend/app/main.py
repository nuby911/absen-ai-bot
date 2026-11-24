from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

import app.models  # noqa: F401
from app.config import KNOWN_DEFAULT_JWT_SECRETS, Settings, get_settings
from app.database import (
    Base,
    create_engine_and_session,
    get_db,
    sync_schema_columns,
)
from app.providers.face_engine import FaceEngine, create_face_engine
from app.providers.llm import LLMProvider, create_llm_provider
from app.providers.whatsapp import WhatsAppProvider, create_whatsapp_provider
from app.routers.admin import router as admin_router
from app.routers.attendance import router as attendance_router
from app.routers.auth import router as auth_router
from app.routers.leaves import router as leaves_router
from app.routers.webhook import router as webhook_router
from app.security import (
    LOGIN_LOCKOUT_SECONDS,
    LOGIN_MAX_FAILURES,
    PIN_LOCKOUT_SECONDS,
    PIN_MAX_FAILURES,
    AttemptRateLimiter,
)

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    face_engine: FaceEngine | None = None,
    whatsapp_provider: WhatsAppProvider | None = None,
    llm_provider: LLMProvider | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    cfg = settings or get_settings()

    @asynccontextmanager
    async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
        if cfg.jwt_secret in KNOWN_DEFAULT_JWT_SECRETS:
            logger.warning(
                "JWT_SECRET masih menggunakan nilai default development. "
                "Harap atur JWT_SECRET yang kuat sebelum deployment produksi."
            )

        if get_db not in fastapi_app.dependency_overrides:
            engine, session_factory = create_engine_and_session(cfg.database_url)
            fastapi_app.state.engine = engine
            fastapi_app.state.session_factory = session_factory
            try:
                async with engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)
                    await conn.run_sync(sync_schema_columns)
                yield
            finally:
                await engine.dispose()
                fastapi_app.state.engine = None
                fastapi_app.state.session_factory = None
        else:
            yield

    app = FastAPI(
        title="Smart School Attendance API",
        version="0.1.0",
        lifespan=lifespan,
    )

    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    app.state.settings = cfg
    app.state.engine = None
    app.state.session_factory = None
    app.state.login_rate_limiter = AttemptRateLimiter(
        max_failures=LOGIN_MAX_FAILURES,
        window_seconds=LOGIN_LOCKOUT_SECONDS,
    )
    app.state.pin_rate_limiter = AttemptRateLimiter(
        max_failures=PIN_MAX_FAILURES,
        window_seconds=PIN_LOCKOUT_SECONDS,
    )
    app.state.face_engine = (
        face_engine if face_engine is not None else create_face_engine(cfg)
    )
    app.state.whatsapp_provider = (
        whatsapp_provider
        if whatsapp_provider is not None
        else create_whatsapp_provider(cfg)
    )
    app.state.llm_provider = (
        llm_provider if llm_provider is not None else create_llm_provider(cfg)
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.get_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def add_security_headers(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_router)
    app.include_router(attendance_router)
    app.include_router(leaves_router)
    app.include_router(webhook_router)

    upload_path = Path(cfg.upload_dir)
    upload_path.mkdir(parents=True, exist_ok=True)
    app.mount("/uploads", StaticFiles(directory=str(upload_path)), name="uploads")

    return app


app = create_app()
