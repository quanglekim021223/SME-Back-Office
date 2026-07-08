from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import (
    TENANT_ID_HEADER,
    USER_ID_HEADER,
    USER_ROLE_HEADER,
    get_current_principal,
    get_tenant_context,
    require_permission,
)
from app.api.responses import APIError
from app.core.auth import Permission, Principal
from app.core.middleware import CORRELATION_ID_HEADER
from app.core.tenant import TenantContext

pytestmark = pytest.mark.integration


def test_correlation_id_is_generated_for_responses(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers[CORRELATION_ID_HEADER]


def test_correlation_id_reuses_incoming_header(client: TestClient) -> None:
    response = client.get(
        "/health",
        headers={CORRELATION_ID_HEADER: "test-correlation-id"},
    )

    assert response.status_code == 200
    assert response.headers[CORRELATION_ID_HEADER] == "test-correlation-id"


def test_cors_preflight_allows_frontend_upload_request(
    client: TestClient,
) -> None:
    response = client.options(
        "/api/v1/documents/upload?filename=invoice.pdf&document_type=invoice",
        headers={
            "Access-Control-Request-Headers": (
                "content-type,x-tenant-id,x-user-id,x-user-role"
            ),
            "Access-Control-Request-Method": "POST",
            "Origin": "http://localhost:3000",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:3000"
    assert "POST" in response.headers["access-control-allow-methods"]


def test_api_error_uses_standard_error_envelope(app: FastAPI) -> None:
    @app.get("/test-error")
    async def test_error() -> None:
        raise APIError(
            status_code=409,
            code="test_conflict",
            message="Test conflict.",
            details={"field": "value"},
        )

    client = TestClient(app)

    response = client.get(
        "/test-error",
        headers={CORRELATION_ID_HEADER: "test-error-correlation-id"},
    )

    assert response.status_code == 409
    assert response.headers[CORRELATION_ID_HEADER] == "test-error-correlation-id"
    assert response.json() == {
        "error": {
            "code": "test_conflict",
            "message": "Test conflict.",
            "details": {"field": "value"},
        },
        "correlation_id": "test-error-correlation-id",
    }


def test_tenant_context_placeholder_reads_tenant_header(app: FastAPI) -> None:
    @app.get("/test-tenant")
    async def test_tenant(
        tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    ) -> dict[str, str | None]:
        return {"tenant_id": tenant_context.tenant_id}

    client = TestClient(app)

    response = client.get(
        "/test-tenant",
        headers={TENANT_ID_HEADER: "tenant_123"},
    )

    assert response.status_code == 200
    assert response.json() == {"tenant_id": "tenant_123"}


def test_authentication_placeholder_reads_user_headers(app: FastAPI) -> None:
    @app.get("/test-principal")
    async def test_principal(
        principal: Annotated[Principal, Depends(get_current_principal)],
    ) -> dict[str, object]:
        return {
            "user_id": principal.user_id,
            "roles": sorted(principal.roles),
            "permissions": sorted(
                permission.value for permission in principal.permissions
            ),
            "is_authenticated": principal.is_authenticated,
        }

    client = TestClient(app)

    response = client.get(
        "/test-principal",
        headers={
            USER_ID_HEADER: "user_123",
            USER_ROLE_HEADER: "member, finance",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "user_123",
        "roles": ["finance", "member"],
        "permissions": [
            "read:health",
            "read:invoices",
            "read:review_tasks",
            "read:tenant",
            "write:documents",
            "write:review_tasks",
        ],
        "is_authenticated": True,
    }


def test_authorization_policy_placeholder_allows_permission(app: FastAPI) -> None:
    @app.get("/test-authorized")
    async def test_authorized(
        principal: Annotated[
            Principal,
            Depends(require_permission(Permission.READ_TENANT)),
        ],
    ) -> dict[str, str | None]:
        return {"user_id": principal.user_id}

    client = TestClient(app)

    response = client.get(
        "/test-authorized",
        headers={
            USER_ID_HEADER: "user_123",
            USER_ROLE_HEADER: "member",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"user_id": "user_123"}


def test_authorization_policy_placeholder_rejects_unauthenticated_user(
    app: FastAPI,
) -> None:
    @app.get("/test-auth-required")
    async def test_auth_required(
        principal: Annotated[
            Principal,
            Depends(require_permission(Permission.READ_TENANT)),
        ],
    ) -> dict[str, str | None]:
        return {"user_id": principal.user_id}

    client = TestClient(app)

    response = client.get("/test-auth-required")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthenticated"


def test_authorization_policy_placeholder_rejects_missing_permission(
    app: FastAPI,
) -> None:
    @app.get("/test-forbidden")
    async def test_forbidden(
        principal: Annotated[
            Principal,
            Depends(require_permission(Permission.READ_TENANT)),
        ],
    ) -> dict[str, str | None]:
        return {"user_id": principal.user_id}

    client = TestClient(app)

    response = client.get(
        "/test-forbidden",
        headers={
            USER_ID_HEADER: "user_123",
            USER_ROLE_HEADER: "viewer",
        },
    )

    assert response.status_code == 403
    assert response.json()["error"] == {
        "code": "permission_denied",
        "message": "Permission denied.",
        "details": {"permission": "read:tenant"},
    }
