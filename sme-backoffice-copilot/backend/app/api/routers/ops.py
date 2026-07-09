"""Local operations and observability API router."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.dependencies import require_permission
from app.core.auth import Permission, Principal
from app.observability.metrics import metrics_registry

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/metrics")
async def get_local_metrics(
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_TENANT)),
    ],
) -> dict[str, object]:
    """Return the process-local metrics snapshot for local operations."""

    del principal
    return metrics_registry.snapshot()
