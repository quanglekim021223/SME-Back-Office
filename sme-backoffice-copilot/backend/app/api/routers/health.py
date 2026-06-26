"""Platform health-check router."""

from typing import cast

from fastapi import APIRouter, Request

from app.core.config import Settings

router = APIRouter(tags=["platform"])


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    """Liveness endpoint for local orchestration and deployment probes."""

    settings = cast(Settings, request.app.state.settings)
    return {"status": "ok", "environment": settings.app_env}
