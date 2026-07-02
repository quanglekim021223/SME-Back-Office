from app.api.dependencies import default_placeholder_permissions, parse_roles
from app.core.auth import Permission, Principal


def test_parse_roles_trims_and_ignores_empty_values() -> None:
    assert parse_roles("admin, finance, ,member") == frozenset(
        {"admin", "finance", "member"}
    )


def test_default_placeholder_permissions_for_member_role() -> None:
    permissions = default_placeholder_permissions(frozenset({"member"}))

    assert permissions == frozenset(
        {
            Permission.READ_HEALTH,
            Permission.READ_REVIEW_TASKS,
            Permission.READ_TENANT,
            Permission.WRITE_DOCUMENTS,
            Permission.WRITE_REVIEW_TASKS,
        }
    )


def test_principal_permission_check() -> None:
    principal = Principal(
        user_id="user_123",
        permissions=frozenset({Permission.READ_HEALTH}),
        is_authenticated=True,
    )

    assert principal.has_permission(Permission.READ_HEALTH)
    assert not principal.has_permission(Permission.READ_TENANT)
