"""Shared FastAPI dependencies."""

from typing import Annotated

from fastapi import Header, Request

from app.core.tenant import TenantContext

TENANT_ID_HEADER = "X-Tenant-ID"


async def get_tenant_context(
    request: Request,
    tenant_id: Annotated[str | None, Header(alias=TENANT_ID_HEADER)] = None,
) -> TenantContext:
    """Return a placeholder tenant context for routes and services.

    Real tenant resolution will be implemented with authentication and
    authorization. For now, this gives downstream code a stable dependency
    boundary without granting permissions.
    """

    tenant_context = TenantContext(tenant_id=tenant_id)
    request.state.tenant_context = tenant_context
    return tenant_context
