"""FastAPI application entry point and composition root."""

from fastapi import FastAPI

from app.api.routers.health import router as health_router
from app.config import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Keeping app construction inside a factory makes tests, future middleware,
    router registration, and dependency wiring easier to control.
    """

    resolved_settings = settings or get_settings()

    app = FastAPI(
        title=resolved_settings.app_name,
        debug=resolved_settings.app_debug,
        version="0.1.0",
    )
    app.state.settings = resolved_settings
    app.include_router(health_router)

    return app


app = create_app()
