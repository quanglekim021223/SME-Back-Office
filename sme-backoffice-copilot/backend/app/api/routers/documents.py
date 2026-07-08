"""Document ingestion API router."""

from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import (
    get_tenant_context,
    require_permission,
    resolve_tenant_uuid,
)
from app.api.responses import APIError
from app.core.auth import Permission, Principal
from app.core.config import Settings
from app.core.db import get_db_session
from app.core.tenant import TenantContext
from app.models.document import DocumentType
from app.observability.tracing import build_trace_provider_from_settings
from app.providers.factory import (
    build_llm_provider_from_settings,
    build_ocr_provider_from_settings,
    build_provider_privacy_gate_from_settings,
    build_provider_routing_config_from_settings,
)
from app.providers.routing import ProviderRuntime
from app.repositories import DocumentRepository, WorkflowRuntimeRepository
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentWorkflowTriggerResponse,
    MalwareScanResponse,
)
from app.services.audit import AuditService
from app.services.document_events import DocumentEventPublisher
from app.services.document_ingestion import (
    DocumentIngestionService,
    DuplicateDocumentError,
    SqlAlchemyDocumentPersistence,
)
from app.services.document_storage import FileValidationError, LocalDocumentStorage
from app.services.workflow_outputs import (
    SqlAlchemyWorkflowOutputPersistence,
    WorkflowOutputPersistenceService,
)
from app.workflows.replay import WorkflowReplayRunner
from app.workflows.triggers import DocumentIngestedWorkflowPublisher

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_storage(request: Request) -> LocalDocumentStorage:
    """Return the configured local document storage adapter."""

    settings = cast(Settings, request.app.state.settings)
    return LocalDocumentStorage.from_settings(settings)


def get_document_workflow_publisher(
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> DocumentEventPublisher:
    """Return local publisher that triggers document workflow after ingestion."""

    settings = cast(Settings, request.app.state.settings)
    workflow_repository = WorkflowRuntimeRepository(session)
    routing_config = build_provider_routing_config_from_settings(settings)
    privacy_gate = build_provider_privacy_gate_from_settings(settings)
    provider_runtime = ProviderRuntime(
        routing_config,
        privacy_gate=privacy_gate,
    )
    trace_provider = build_trace_provider_from_settings(settings)
    from app.providers import ProviderPrivacyContext
    runner = WorkflowReplayRunner(
        persistence=workflow_repository,
        provider_runtime=provider_runtime,
        llm_provider=build_llm_provider_from_settings(settings),
        ocr_provider=build_ocr_provider_from_settings(settings),
        provider_privacy_context=ProviderPrivacyContext(
            tenant_allows_cloud=True,
        ),
        trace_provider=trace_provider,
    )
    return DocumentIngestedWorkflowPublisher(
        runner=runner,
        output_persistence_service=WorkflowOutputPersistenceService(
            SqlAlchemyWorkflowOutputPersistence(session),
            trace_provider=trace_provider,
        ),
        commit=workflow_repository.commit,
    )


def get_document_ingestion_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[LocalDocumentStorage, Depends(get_document_storage)],
    event_publisher: Annotated[
        DocumentEventPublisher,
        Depends(get_document_workflow_publisher),
    ],
) -> DocumentIngestionService:
    """Return the document ingestion application service."""

    return DocumentIngestionService(
        persistence=SqlAlchemyDocumentPersistence(session),
        storage=storage,
        event_publisher=event_publisher,
    )


def map_file_validation_error(exc: FileValidationError) -> APIError:
    """Map file validation failures to HTTP API errors."""

    status_code = status.HTTP_400_BAD_REQUEST
    if exc.code == "FILE_TOO_LARGE":
        status_code = status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    if exc.code == "UNSUPPORTED_MIME_TYPE":
        status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE

    return APIError(
        status_code=status_code,
        code=exc.code.lower(),
        message=exc.detail,
    )


@router.post(
    "/upload",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentUploadResponse,
)
async def upload_document(
    request: Request,
    filename: Annotated[str, Query(min_length=1)],
    document_type: Annotated[DocumentType, Query()] = DocumentType.OTHER,
    tenant_context: Annotated[TenantContext | None, Depends(get_tenant_context)] = None,
    principal: Annotated[
        Principal | None,
        Depends(require_permission(Permission.WRITE_DOCUMENTS)),
    ] = None,
    service: Annotated[
        DocumentIngestionService | None,
        Depends(get_document_ingestion_service),
    ] = None,
) -> DocumentUploadResponse:
    """Accept an uploaded document body and persist local document metadata."""

    del principal
    assert tenant_context is not None
    assert service is not None

    tenant_id = resolve_tenant_uuid(tenant_context)
    media_type = request.headers.get("content-type", "")
    content = await request.body()

    try:
        result = await service.upload_document(
            tenant_id=tenant_id,
            filename=filename,
            content=content,
            media_type=media_type,
            document_type=document_type,
        )
    except DuplicateDocumentError as exc:
        raise APIError(
            status_code=status.HTTP_409_CONFLICT,
            code="duplicate_document",
            message="A document with the same content already exists for this tenant.",
            details={"document_id": str(exc.existing_document.id)},
        ) from exc
    except FileValidationError as exc:
        raise map_file_validation_error(exc) from exc

    document = result.document
    malware_scan_result = result.malware_scan_result
    document_ingested_event = result.document_ingested_event

    AuditService().log_document_uploaded(
        tenant_id=tenant_id,
        actor_id=getattr(tenant_context.principal, "user_id", None)
        if tenant_context.principal
        else None,
        document_id=document.id,
        filename=document.original_filename,
        correlation_id=getattr(request.state, "correlation_id", None),
    )

    return DocumentUploadResponse(
        id=document.id,
        tenant_id=document.tenant_id,
        document_type=document.document_type,
        status=document.status,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        content_hash=document.content_hash,
        storage_uri=result.artifact.storage_uri,
        malware_scan=MalwareScanResponse(
            status=malware_scan_result.status.value,
            scanner_name=malware_scan_result.scanner_name,
            scanner_version=malware_scan_result.scanner_version,
            scanned_at=malware_scan_result.scanned_at,
            signature_version=malware_scan_result.signature_version,
            threats=list(malware_scan_result.threats),
            details=malware_scan_result.details,
        ),
        workflow_trigger=DocumentWorkflowTriggerResponse(
            event_id=document_ingested_event.event_id,
            event_name=document_ingested_event.event_name,
            document_id=document_ingested_event.document_id,
        ),
    )


@router.get(
    "/{document_id}/download",
    response_class=FileResponse,
)
async def download_document(
    document_id: UUID,
    tenant_context: Annotated[TenantContext, Depends(get_tenant_context)],
    principal: Annotated[
        Principal,
        Depends(require_permission(Permission.READ_INVOICES)),
    ],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[LocalDocumentStorage, Depends(get_document_storage)],
) -> FileResponse:
    """Download the original uploaded file for a tenant-scoped document."""

    from app.services.audit import AuditEvent

    del principal
    tenant_id = resolve_tenant_uuid(tenant_context)
    repository = DocumentRepository(session)
    document = await repository.get_with_artifacts(
        tenant_id=tenant_id,
        document_id=document_id,
    )

    if document is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="document_not_found",
            message="Document was not found.",
            details={"document_id": str(document_id)},
        )

    # Find the original artifact
    original_artifact = next(
        (art for art in document.artifacts if art.artifact_type == "original"),
        None,
    )
    if original_artifact is None:
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="artifact_not_found",
            message="Original document file was not found.",
            details={"document_id": str(document_id)},
        )

    # Parse local:// storage URI to get the filesystem path
    if not original_artifact.storage_uri.startswith("local://"):
        raise APIError(
            status_code=status.HTTP_400_BAD_REQUEST,
            code="unsupported_storage",
            message="Document is not stored locally.",
        )

    object_key = original_artifact.storage_uri[8:]  # strip local://
    file_path = storage.root_path / object_key

    if not file_path.exists():
        raise APIError(
            status_code=status.HTTP_404_NOT_FOUND,
            code="file_not_found",
            message="File does not exist on disk.",
        )

    # Emit audit log for export/download
    AuditService().log(
        AuditEvent(
            event="document.downloaded",
            tenant_id=str(tenant_id),
            actor_id=tenant_context.principal.user_id if tenant_context.principal else None,
            resource_type="document",
            resource_id=str(document_id),
            extra={"filename": document.original_filename},
        )
    )

    return FileResponse(
        path=file_path,
        media_type=document.mime_type,
        filename=document.original_filename,
    )

