from pathlib import Path
from uuid import uuid4

import pytest

from app.models.document import (
    ArtifactType,
    Document,
    DocumentArtifact,
    DocumentStatus,
    DocumentType,
)
from app.services.document_events import DocumentIngested
from app.services.document_ingestion import (
    DocumentIngestionService,
    DuplicateDocumentError,
)
from app.services.document_storage import (
    FileValidationError,
    LocalDocumentStorage,
    compute_content_hash,
)
from app.services.malware_scan import MalwareScanStatus


class FakeDocumentPersistence:
    def __init__(self, existing_document: Document | None = None) -> None:
        self.existing_document = existing_document
        self.documents: list[Document] = []
        self.artifacts: list[DocumentArtifact] = []
        self.committed = False

    async def get_by_tenant_and_content_hash(
        self,
        *,
        tenant_id,
        content_hash: str,
    ) -> Document | None:
        del tenant_id, content_hash
        return self.existing_document

    def add_document(self, document: Document) -> Document:
        self.documents.append(document)
        return document

    def add_artifact(self, artifact: DocumentArtifact) -> DocumentArtifact:
        self.artifacts.append(artifact)
        return artifact

    async def commit(self) -> None:
        self.committed = True


class FakeDocumentEventPublisher:
    def __init__(self) -> None:
        self.events: list[DocumentIngested] = []

    async def publish_document_ingested(self, event: DocumentIngested) -> None:
        self.events.append(event)


def create_service(
    *,
    root_path: Path,
    persistence: FakeDocumentPersistence,
    allowed_mime_types: set[str] | None = None,
    event_publisher: FakeDocumentEventPublisher | None = None,
) -> DocumentIngestionService:
    storage = LocalDocumentStorage(
        root_path=root_path,
        max_size_bytes=1024,
        allowed_mime_types=allowed_mime_types or {"application/pdf"},
    )
    return DocumentIngestionService(
        persistence=persistence,
        storage=storage,
        event_publisher=event_publisher,
    )


@pytest.mark.asyncio
async def test_document_ingestion_stores_file_and_creates_accepted_document(
    tmp_path,
) -> None:
    persistence = FakeDocumentPersistence()
    event_publisher = FakeDocumentEventPublisher()
    service = create_service(
        root_path=tmp_path,
        persistence=persistence,
        event_publisher=event_publisher,
    )
    tenant_id = uuid4()
    content = b"%PDF-1.4 sample"

    result = await service.upload_document(
        tenant_id=tenant_id,
        filename="invoice.pdf",
        content=content,
        media_type="application/pdf",
        document_type=DocumentType.INVOICE,
    )

    assert result.stored_file.path.read_bytes() == content
    assert result.document in persistence.documents
    assert result.document.tenant_id == tenant_id
    assert result.document.document_type == DocumentType.INVOICE.value
    assert result.document.status == DocumentStatus.ACCEPTED.value
    assert result.document.content_hash == compute_content_hash(content)
    assert result.artifact in persistence.artifacts
    assert result.artifact.document_id == result.document.id
    assert result.artifact.artifact_type == ArtifactType.ORIGINAL.value
    assert result.artifact.storage_uri.startswith("local://")
    assert result.malware_scan_result.status == MalwareScanStatus.NOT_SCANNED
    assert result.artifact.metadata_ is not None
    malware_scan_metadata = result.artifact.metadata_["malware_scan"]
    assert isinstance(malware_scan_metadata, dict)
    assert malware_scan_metadata["status"] == MalwareScanStatus.NOT_SCANNED.value
    assert persistence.committed is True
    assert event_publisher.events == [result.document_ingested_event]
    assert result.document_ingested_event.event_name == "DocumentIngested"
    assert result.document_ingested_event.tenant_id == tenant_id
    assert result.document_ingested_event.document_id == result.document.id
    assert result.document_ingested_event.storage_uri == result.artifact.storage_uri


@pytest.mark.asyncio
async def test_document_ingestion_rejects_duplicate_before_storing_file(
    tmp_path,
) -> None:
    existing_document = Document(
        id=uuid4(),
        tenant_id=uuid4(),
        document_type=DocumentType.INVOICE.value,
        status=DocumentStatus.ACCEPTED.value,
        original_filename="invoice.pdf",
        mime_type="application/pdf",
        size_bytes=10,
        content_hash="existing-hash",
    )
    persistence = FakeDocumentPersistence(existing_document=existing_document)
    event_publisher = FakeDocumentEventPublisher()
    service = create_service(
        root_path=tmp_path,
        persistence=persistence,
        event_publisher=event_publisher,
    )

    with pytest.raises(DuplicateDocumentError) as exc_info:
        await service.upload_document(
            tenant_id=uuid4(),
            filename="invoice.pdf",
            content=b"%PDF duplicate",
            media_type="application/pdf",
            document_type=DocumentType.INVOICE,
        )

    assert exc_info.value.existing_document is existing_document
    assert persistence.documents == []
    assert persistence.artifacts == []
    assert persistence.committed is False
    assert list(tmp_path.rglob("*")) == []
    assert event_publisher.events == []


@pytest.mark.asyncio
async def test_document_ingestion_rejects_unsupported_mime_type(tmp_path) -> None:
    persistence = FakeDocumentPersistence()
    service = create_service(root_path=tmp_path, persistence=persistence)

    with pytest.raises(FileValidationError) as exc_info:
        await service.upload_document(
            tenant_id=uuid4(),
            filename="script.sh",
            content=b"echo unsafe",
            media_type="text/x-shellscript",
            document_type=DocumentType.OTHER,
        )

    assert exc_info.value.code == "UNSUPPORTED_MIME_TYPE"
    assert persistence.documents == []
    assert persistence.artifacts == []
