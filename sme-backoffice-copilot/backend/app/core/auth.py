"""Authentication and authorization placeholders.

These types intentionally model the boundary for future OIDC/JWT/RBAC work
without claiming to provide production authentication yet.
"""

from dataclasses import dataclass, field
from enum import StrEnum


class Permission(StrEnum):
    """Permission names used by API authorization policy."""

    READ_HEALTH = "read:health"
    READ_TENANT = "read:tenant"


@dataclass(frozen=True)
class Principal:
    """Authenticated actor resolved for the current request.

    The current implementation is a development placeholder. A production
    implementation must derive this from a verified token/session and tenant
    membership, not from caller-controlled headers alone.
    """

    user_id: str | None = None
    subject: str | None = None
    roles: frozenset[str] = field(default_factory=frozenset)
    permissions: frozenset[Permission] = field(default_factory=frozenset)
    is_authenticated: bool = False

    def has_permission(self, permission: Permission) -> bool:
        """Return whether the principal has a permission."""

        return permission in self.permissions
