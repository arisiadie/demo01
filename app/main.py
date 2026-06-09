from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    initialize_runtime_services,
    router,
    start_due_notification_scheduler,
    stop_due_notification_scheduler,
)
from app.core.config import settings
from app.core.database import Base, engine
from app.models import entities  # noqa: F401
from app.services.rate_limit import InMemoryRateLimitMiddleware



def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="生产级内测定位的口腔医疗 Agentic RAG 多智能体平台",
        version="0.1.0",
    )
    Base.metadata.create_all(bind=engine)
    settings.resolved_upload_dir.mkdir(parents=True, exist_ok=True)

    app.add_middleware(InMemoryRateLimitMiddleware)
    app.include_router(router, prefix="/api")
    app.mount("/static", StaticFiles(directory="app/static"), name="static")

    @app.on_event("startup")
    async def startup_runtime_services() -> None:
        initialize_runtime_services()
        start_due_notification_scheduler()

    @app.on_event("shutdown")
    async def shutdown_runtime_services() -> None:
        await stop_due_notification_scheduler()

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse("app/static/index.html")

    return app


app = create_app()
