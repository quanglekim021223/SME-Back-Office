"""FastAPI application entry point.

Only platform-level endpoints belong here. Domain routes are composed from the
``routes`` package as they are implemented.
"""

from fastapi import FastAPI

from app.config import get_settings

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    debug=settings.app_debug,
    version="0.1.0",
)


@app.get("/health", tags=["platform"])
async def health() -> dict[str, str]:
    """Liveness endpoint for local orchestration and deployment probes."""

    return {"status": "ok", "environment": settings.app_env}
