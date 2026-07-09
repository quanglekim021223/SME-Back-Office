"""Integration tests for document download API endpoint."""

from __future__ import annotations

import logging
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.dependencies import get_tenant_context, require_permission
from app.core.auth import Permission, Principal
from app.core.db import get_db_session
from app.core.tenant import TenantContext
from app.models.document import Document, DocumentArtifact
from app.repositories.documents import DocumentRepository
from app.services.document_storage import LocalDocumentStorage


@pytest.fixture
def download_app(app: FastAPI) -> FastAPI:
    """Return the application with clean overrides."""
    app.dependency_overrides.clear()
    return app


def auth_headers(tenant_id: str | None = None) -> dict[str, str]:
    """Return mock auth headers for local development principal."""
    headers = {
        "X-User-ID": "test-admin",
        "X-User-Role": "admin",
    }
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id
    return headers


def test_download_document_success(download_app: FastAPI, client: TestClient, tmp_path) -> None:
    """Download endpoint streams file and logs audit event when authorized."""

    tenant_id = uuid4()
    document_id = uuid4()

    # Create dummy original file
    file_content = b"original PDF body content"
    object_key = f"tenants/{tenant_id}/documents/{document_id}/original/invoice.pdf"
    dummy_file = tmp_path / object_key
    dummy_file.parent.mkdir(parents=True, exist_ok=True)
    dummy_file.write_bytes(file_content)

    # Mock Document and DocumentArtifact
    mock_artifact = MagicMock(spec=DocumentArtifact)
    mock_artifact.artifact_type = "original"
    mock_artifact.storage_uri = f"local://tenants/{tenant_id}/documents/{document_id}/original/invoice.pdf"

    mock_doc = MagicMock(spec=Document)
    mock_doc.id = document_id
    mock_doc.tenant_id = tenant_id
    mock_doc.original_filename = "invoice.pdf"
    mock_doc.mime_type = "application/pdf"
    mock_doc.artifacts = [mock_artifact]

    # Mock repository
    mock_repo = MagicMock(spec=DocumentRepository)
    mock_repo.get_with_artifacts = AsyncMock(return_value=mock_doc)

    # Use real LocalDocumentStorage to avoid mock path resolution issues
    mock_storage = LocalDocumentStorage(
        root_path=tmp_path,
        max_size_bytes=10 * 1024 * 1024,
        allowed_mime_types=["application/pdf"],
    )

    # Override dependencies
    from app.api.routers.documents import get_document_storage
    download_app.dependency_overrides[get_db_session] = lambda: MagicMock()
    download_app.dependency_overrides[get_document_storage] = lambda: mock_storage

    # Injecting the mock repository
    with patch("app.api.routers.documents.DocumentRepository") as mock_repo_class:
        mock_repo_class.return_value = mock_repo
        with patch("app.services.audit.AuditService.log") as mock_audit_log:
            response = client.get(
                f"/api/v1/documents/{document_id}/download",
                headers=auth_headers(str(tenant_id)),
            )

            if response.status_code != 200:
                print("RESPONSE ERROR DETAIL:", response.json())
            assert response.status_code == 200
            assert response.content == file_content
            assert response.headers["content-type"] == "application/pdf"
            assert "attachment" in response.headers["content-disposition"]
            assert "invoice.pdf" in response.headers["content-disposition"]

            # Verify audit logging
            mock_audit_log.assert_called_once()
            audit_event = mock_audit_log.call_args[0][0]
            assert audit_event.event == "document.downloaded"
            assert audit_event.tenant_id == str(tenant_id)
            assert audit_event.resource_id == str(document_id)
            assert audit_event.extra == {"filename": "invoice.pdf"}


def test_download_document_cross_tenant_returns_404(download_app: FastAPI, client: TestClient) -> None:
    """Requesting document download with a tenant ID that does not own it returns 404."""

    tenant_id = uuid4()
    document_id = uuid4()

    # Mock repository returning None for cross-tenant access
    mock_repo = MagicMock(spec=DocumentRepository)
    mock_repo.get_with_artifacts = AsyncMock(return_value=None)

    with patch("app.api.routers.documents.DocumentRepository", return_value=mock_repo):
        response = client.get(
            f"/api/v1/documents/{document_id}/download",
            headers=auth_headers(str(tenant_id)),
        )

        assert response.status_code == 404
        payload = response.json()
        assert payload["error"]["code"] == "document_not_found"
