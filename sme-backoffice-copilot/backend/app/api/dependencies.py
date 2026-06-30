"""Shared FastAPI dependencies."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastapi import Depends, Header, Request, status

from app.api.responses import APIError
from app.core.auth import Permission, Principal
from app.core.tenant import TenantContext

TENANT_ID_HEADER = "X-Tenant-ID"
USER_ID_HEADER = "X-User-ID"
USER_ROLE_HEADER = "X-User-Role"


def parse_roles(raw_roles: str | None) -> frozenset[str]:
    """Parse a comma-separated placeholder roles header."""

    if raw_roles is None:
        return frozenset()
    return frozenset(role.strip() for role in raw_roles.split(",") if role.strip())


def default_placeholder_permissions(roles: frozenset[str]) -> frozenset[Permission]:
    """Return development-only permissions for placeholder principals."""

    permissions = {Permission.READ_HEALTH}
    if "admin" in roles or "member" in roles:
        permissions.add(Permission.READ_TENANT)
        permissions.add(Permission.WRITE_DOCUMENTS)
    return frozenset(permissions)


async def get_current_principal(
    request: Request,
    user_id: Annotated[str | None, Header(alias=USER_ID_HEADER)] = None,
    raw_roles: Annotated[str | None, Header(alias=USER_ROLE_HEADER)] = None,
) -> Principal:
    """Return a placeholder authenticated principal.

    Real authentication will verify a token/session. For now, this dependency
    creates a stable boundary for route code and tests.
    """

    roles = parse_roles(raw_roles)
    principal = Principal(
        user_id=user_id,
        subject=user_id,
        roles=roles,
        permissions=default_placeholder_permissions(roles),
        is_authenticated=user_id is not None,
    )
    request.state.principal = principal
    return principal


async def get_tenant_context(
    request: Request,
    principal: Annotated[Principal, Depends(get_current_principal)],
    tenant_id: Annotated[str | None, Header(alias=TENANT_ID_HEADER)] = None,
) -> TenantContext:
    """Return a placeholder tenant context for routes and services.

    Real tenant resolution will be implemented with authentication and
    authorization. For now, this gives downstream code a stable dependency
    boundary without granting permissions.
    """

    tenant_context = TenantContext(tenant_id=tenant_id, principal=principal)
    request.state.tenant_context = tenant_context
    return tenant_context


def require_permission(
    permission: Permission,
) -> Callable[[Principal], Awaitable[Principal]]:
    """Create a dependency that requires one placeholder permission."""

    async def dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> Principal:
        if not principal.is_authenticated:
            raise APIError(
                status_code=status.HTTP_401_UNAUTHORIZED,
                code="unauthenticated",
                message="Authentication is required.",
            )
        if not principal.has_permission(permission):
            raise APIError(
                status_code=status.HTTP_403_FORBIDDEN,
                code="permission_denied",
                message="Permission denied.",
                details={"permission": permission.value},
            )
        return principal

    return dependency
