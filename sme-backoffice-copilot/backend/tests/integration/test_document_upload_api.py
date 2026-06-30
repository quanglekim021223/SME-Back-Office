from pathlib import Path
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.documents import get_document_ingestion_service
from app.models.document import ArtifactType, Document, DocumentArtifact, DocumentStatus
from app.services.document_events import DocumentIngested
from app.services.document_ingestion import DocumentUploadResult, DuplicateDocumentError
from app.services.document_storage import FileValidationError, StoredFile
from app.services.malware_scan import MalwareScanResult, MalwareScanStatus


class FakeDocumentIngestionService:
    def __init__(
        self,
        *,
        result: DocumentUploadResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[dict[str, object]] = []

    async def upload_document(
        self,
        *,
        tenant_id: UUID,
        filename: str,
        content: bytes,
        media_type: str,
        document_type,
    ) -> DocumentUploadResult:
        self.calls.append(
            {
                "tenant_id": tenant_id,
                "filename": filename,
                "content": content,
                "media_type": media_type,
                "document_type": document_type,
            }
        )
        if self.error is not None:
            raise self.error
        assert self.result is not None
        return self.result


def auth_headers(tenant_id: UUID | None = None, media_type: str = "application/pdf"):
    return {
        "X-Tenant-ID": str(tenant_id or uuid4()),
        "X-User-ID": str(uuid4()),
        "X-User-Role": "member",
        "Content-Type": media_type,
    }


def build_upload_result(tenant_id: UUID) -> DocumentUploadResult:
    document_id = uuid4()
    document = Document(
        id=document_id,
        tenant_id=tenant_id,
        document_type="invoice",
        status=DocumentStatus.ACCEPTED.value,
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=12,
        content_hash="hash-123",
    )
    artifact = DocumentArtifact(
        id=uuid4(),
        tenant_id=tenant_id,
        document_id=document_id,
        artifact_type=ArtifactType.ORIGINAL.value,
        storage_uri="local://tenants/t/documents/d/original/invoice.pdf",
        media_type="application/pdf",
        size_bytes=12,
        content_hash="hash-123",
    )
    stored_file = StoredFile(
        object_key="tenants/t/documents/d/original/invoice.pdf",
        storage_uri=artifact.storage_uri,
        path=Path("unused"),
        filename="invoice.pdf",
        media_type="application/pdf",
        size_bytes=12,
        content_hash="hash-123",
    )
    malware_scan_result = MalwareScanResult(
        status=MalwareScanStatus.NOT_SCANNED,
        scanner_name="placeholder",
        scanner_version="0.0.0",
    )
    document_ingested_event = DocumentIngested(
        tenant_id=tenant_id,
        document_id=document_id,
        document_type=document.document_type,
        content_hash=document.content_hash,
        storage_uri=artifact.storage_uri,
        malware_scan_status=malware_scan_result.status.value,
    )
    return DocumentUploadResult(
        document=document,
        artifact=artifact,
        stored_file=stored_file,
        malware_scan_result=malware_scan_result,
        document_ingested_event=document_ingested_event,
    )


@pytest.fixture
def upload_app(app: FastAPI):
    yield app
    app.dependency_overrides.clear()


def test_upload_document_endpoint_accepts_raw_file_body(
    upload_app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id = uuid4()
    fake_service = FakeDocumentIngestionService(result=build_upload_result(tenant_id))
    upload_app.dependency_overrides[get_document_ingestion_service] = lambda: (
        fake_service
    )

    response = client.post(
        "/api/v1/documents/upload?filename=invoice.pdf&document_type=invoice",
        headers=auth_headers(tenant_id),
        content=b"invoice body",
    )

    assert response.status_code == 201
    payload = response.json()
    assert payload["tenant_id"] == str(tenant_id)
    assert payload["document_type"] == "invoice"
    assert payload["status"] == DocumentStatus.ACCEPTED.value
    assert (
        payload["storage_uri"] == "local://tenants/t/documents/d/original/invoice.pdf"
    )
    assert payload["malware_scan"]["status"] == MalwareScanStatus.NOT_SCANNED.value
    assert payload["malware_scan"]["scanner_name"] == "placeholder"
    assert payload["workflow_trigger"]["event_name"] == "DocumentIngested"
    assert payload["duplicate"] is False
    assert fake_service.calls[0]["content"] == b"invoice body"


def test_upload_document_endpoint_returns_conflict_for_duplicate(
    upload_app: FastAPI,
    client: TestClient,
) -> None:
    existing_document = Document(
        id=uuid4(),
        tenant_id=uuid4(),
        document_type="invoice",
        status=DocumentStatus.ACCEPTED.value,
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=12,
        content_hash="hash-123",
    )
    fake_service = FakeDocumentIngestionService(
        error=DuplicateDocumentError(existing_document)
    )
    upload_app.dependency_overrides[get_document_ingestion_service] = lambda: (
        fake_service
    )

    response = client.post(
        "/api/v1/documents/upload?filename=invoice.pdf&document_type=invoice",
        headers=auth_headers(),
        content=b"invoice body",
    )

    assert response.status_code == 409
    payload = response.json()
    assert payload["error"]["code"] == "duplicate_document"
    assert payload["error"]["details"] == {"document_id": str(existing_document.id)}


def test_upload_document_endpoint_returns_unsupported_media_type(
    upload_app: FastAPI,
    client: TestClient,
) -> None:
    fake_service = FakeDocumentIngestionService(
        error=FileValidationError(
            code="UNSUPPORTED_MIME_TYPE",
            detail="Unsupported MIME type: application/x-msdownload.",
        )
    )
    upload_app.dependency_overrides[get_document_ingestion_service] = lambda: (
        fake_service
    )

    response = client.post(
        "/api/v1/documents/upload?filename=malware.exe",
        headers=auth_headers(media_type="application/x-msdownload"),
        content=b"unsafe",
    )

    assert response.status_code == 415
    payload = response.json()
    assert payload["error"]["code"] == "unsupported_mime_type"
