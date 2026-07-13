"""Document ingestion service for local upload workflows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import (
    ArtifactType,
    Document,
    DocumentArtifact,
    DocumentStatus,
    DocumentType,
)
from app.repositories.documents import DocumentRepository
from app.services.document_events import (
    DocumentEventPublisher,
    DocumentIngested,
    NoopDocumentEventPublisher,
    WorkflowJobSubmission,
)
from app.services.document_storage import (
    LocalDocumentStorage,
    StoredFile,
    compute_content_hash,
    validate_file_size,
    validate_mime_type,
)
from app.services.malware_scan import (
    MalwareScanner,
    MalwareScanResult,
    PlaceholderMalwareScanner,
)


class DocumentPersistence(Protocol):
    """Persistence boundary used by document ingestion."""

    async def get_by_tenant_and_content_hash(
        self,
        *,
        tenant_id: UUID,
        content_hash: str,
    ) -> Document | None:
        """Return an existing document for duplicate detection."""

    def add_document(self, document: Document) -> Document:
        """Stage a document for insertion."""

    def add_artifact(self, artifact: DocumentArtifact) -> DocumentArtifact:
        """Stage a document artifact for insertion."""

    async def commit(self) -> None:
        """Commit staged persistence changes."""


class SqlAlchemyDocumentPersistence:
    """SQLAlchemy-backed persistence adapter for document ingestion."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repository = DocumentRepository(session)

    async def get_by_tenant_and_content_hash(
        self,
        *,
        tenant_id: UUID,
        content_hash: str,
    ) -> Document | None:
        """Return an existing document for duplicate detection."""

        return await self.repository.get_by_tenant_and_content_hash(
            tenant_id=tenant_id,
            content_hash=content_hash,
        )

    def add_document(self, document: Document) -> Document:
        """Stage a document for insertion."""

        return self.repository.add(document)

    def add_artifact(self, artifact: DocumentArtifact) -> DocumentArtifact:
        """Stage a document artifact for insertion."""

        return self.repository.add_artifact(artifact)

    async def commit(self) -> None:
        """Commit staged changes."""

        await self.session.commit()


@dataclass(frozen=True, slots=True)
class DocumentUploadResult:
    """Result returned after a successful document upload."""

    document: Document
    artifact: DocumentArtifact
    stored_file: StoredFile
    malware_scan_result: MalwareScanResult
    document_ingested_event: DocumentIngested
    workflow_job_submission: WorkflowJobSubmission | None = None


class DuplicateDocumentError(Exception):
    """Raised when a tenant uploads a document that already exists."""

    def __init__(self, existing_document: Document) -> None:
        self.existing_document = existing_document
        super().__init__("A document with the same content already exists.")


class DocumentIngestionService:
    """Application service for validating and ingesting uploaded documents."""

    def __init__(
        self,
        *,
        persistence: DocumentPersistence,
        storage: LocalDocumentStorage,
        malware_scanner: MalwareScanner | None = None,
        event_publisher: DocumentEventPublisher | None = None,
    ) -> None:
        self.persistence = persistence
        self.storage = storage
        self.malware_scanner = malware_scanner or PlaceholderMalwareScanner()
        self.event_publisher = event_publisher or NoopDocumentEventPublisher()

    async def upload_document(
        self,
        *,
        tenant_id: UUID,
        filename: str,
        content: bytes,
        media_type: str,
        document_type: DocumentType,
        correlation_id: str | None = None,
    ) -> DocumentUploadResult:
        """Validate, de-duplicate, store, and persist uploaded document metadata."""

        size_bytes = len(content)
        validate_file_size(size_bytes, self.storage.max_size_bytes)
        normalized_media_type = validate_mime_type(
            media_type,
            self.storage.allowed_mime_types,
        )
        content_hash = compute_content_hash(content)

        existing_document = await self.persistence.get_by_tenant_and_content_hash(
            tenant_id=tenant_id,
            content_hash=content_hash,
        )
        if existing_document is not None:
            raise DuplicateDocumentError(existing_document)

        malware_scan_result = await self.malware_scanner.scan(
            filename=filename,
            content=content,
            media_type=normalized_media_type,
        )

        document_id = uuid4()
        stored_file = self.storage.store(
            tenant_id=tenant_id,
            document_id=document_id,
            filename=filename,
            content=content,
            media_type=normalized_media_type,
        )

        document = Document(
            id=document_id,
            tenant_id=tenant_id,
            document_type=document_type.value,
            status=DocumentStatus.ACCEPTED.value,
            original_filename=filename,
            mime_type=stored_file.media_type,
            size_bytes=stored_file.size_bytes,
            content_hash=stored_file.content_hash,
            source_system="local_upload",
        )
        artifact = DocumentArtifact(
            tenant_id=tenant_id,
            document_id=document_id,
            artifact_type=ArtifactType.ORIGINAL.value,
            storage_uri=stored_file.storage_uri,
            media_type=stored_file.media_type,
            size_bytes=stored_file.size_bytes,
            content_hash=stored_file.content_hash,
            metadata_={
                "object_key": stored_file.object_key,
                "filename": stored_file.filename,
                "malware_scan": malware_scan_result.to_metadata(),
            },
        )

        self.persistence.add_document(document)
        self.persistence.add_artifact(artifact)

        document_ingested_event = DocumentIngested(
            tenant_id=tenant_id,
            document_id=document_id,
            document_type=document.document_type,
            content_hash=document.content_hash,
            storage_uri=artifact.storage_uri,
            malware_scan_status=malware_scan_result.status.value,
            local_path=str(stored_file.path),
            correlation_id=correlation_id,
        )
        workflow_job_submission = await self.event_publisher.publish_document_ingested(
            document_ingested_event
        )
        # Document metadata, WorkflowRun, WorkflowJob, and OutboxEvent share the
        # request session and are committed atomically here.
        await self.persistence.commit()

        return DocumentUploadResult(
            document=document,
            artifact=artifact,
            stored_file=stored_file,
            malware_scan_result=malware_scan_result,
            document_ingested_event=document_ingested_event,
            workflow_job_submission=workflow_job_submission,
        )
