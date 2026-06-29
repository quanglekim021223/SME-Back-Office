"""Tenant context placeholder.

This module intentionally does not implement real authorization yet. It defines
the request-scoped shape that future authentication and authorization will fill.
"""

from dataclasses import dataclass

from app.core.auth import Principal


@dataclass(frozen=True)
class TenantContext:
    """Tenant information resolved for the current request."""

    tenant_id: str | None = None
    principal: Principal | None = None
