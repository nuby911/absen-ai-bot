from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import Settings, get_settings
from app.providers.face_engine import FaceEngine, create_face_engine
from app.routers.admin import router as admin_router
from app.routers.auth import router as auth_router


def create_app(
    settings: Settings | None = None,
    face_engine: FaceEngine | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application instance."""
    cfg = settings or get_settings()
    app = FastAPI(
        title="Smart School Attendance API",
        version="0.1.0",
    )

    if settings is not None:
        app.dependency_overrides[get_settings] = lambda: settings

    app.state.settings = cfg
    app.state.face_engine = (
        face_engine if face_engine is not None else create_face_engine(cfg)
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health")
    async def health_check() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth_router)
    app.include_router(admin_router)

    upload_path = Path(cfg.upload_dir)
    if upload_path.exists() and upload_path.is_dir():
        app.mount("/uploads", StaticFiles(directory=str(upload_path)), name="uploads")

    return app


app = create_app()
