from typing import Annotated

from fastapi import Depends
from fastapi.testclient import TestClient

from app.api.dependencies import TENANT_ID_HEADER, get_tenant_context
from app.api.responses import APIError
from app.core.middleware import CORRELATION_ID_HEADER
from app.core.tenant import TenantContext
from app.main import create_app


def test_correlation_id_is_generated_for_responses() -> None:
    client = TestClient(create_app())

    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers[CORRELATION_ID_HEADER]


def test_correlation_id_reuses_incoming_header() -> None:
    client = TestClient(create_app())

    response = client.get(
        "/health",
        headers={CORRELATION_ID_HEADER: "test-correlation-id"},
    )

    assert response.status_code == 200
    assert response.headers[CORRELATION_ID_HEADER] == "test-correlation-id"


def test_api_error_uses_standard_error_envelope() -> None:
    app = create_app()

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


def test_tenant_context_placeholder_reads_tenant_header() -> None:
    app = create_app()

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
