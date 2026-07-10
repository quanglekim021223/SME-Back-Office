"""FastAPI application entry point and composition root."""

from fastapi import FastAPI

from app.api.exception_handlers import register_exception_handlers
from app.api.routers.documents import router as documents_router
from app.api.routers.health import router as health_router
from app.api.routers.invoices import router as invoices_router
from app.api.routers.ops import router as ops_router
from app.api.routers.review_tasks import router as review_tasks_router
from app.api.routers.workflows import router as workflows_router
from app.core.config import Settings, get_settings
from app.core.middleware import register_middleware
from app.observability.logging_filter import (
    setup_logging_redaction,
    setup_structured_logging,
)


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application instance.

    Keeping app construction inside a factory makes tests, future middleware,
    router registration, and dependency wiring easier to control.
    """

    resolved_settings = settings or get_settings()
    setup_structured_logging(log_format=resolved_settings.log_format.value)
    setup_logging_redaction()

    app = FastAPI(
        title=resolved_settings.app_name,
        debug=resolved_settings.app_debug,
        version="0.1.0",
    )
    app.state.settings = resolved_settings

    register_middleware(app)
    register_exception_handlers(app)
    app.include_router(documents_router, prefix=resolved_settings.app_api_prefix)
    app.include_router(invoices_router, prefix=resolved_settings.app_api_prefix)
    app.include_router(review_tasks_router, prefix=resolved_settings.app_api_prefix)
    app.include_router(workflows_router, prefix=resolved_settings.app_api_prefix)
    app.include_router(ops_router, prefix=resolved_settings.app_api_prefix)
    app.include_router(health_router)

    return app


app = create_app()
