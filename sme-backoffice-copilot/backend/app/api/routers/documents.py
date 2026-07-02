"""Document ingestion API router."""

from typing import Annotated, cast

from fastapi import APIRouter, Depends, Query, Request, status
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
from app.schemas.document import (
    DocumentUploadResponse,
    DocumentWorkflowTriggerResponse,
    MalwareScanResponse,
)
from app.services.document_ingestion import (
    DocumentIngestionService,
    DuplicateDocumentError,
    SqlAlchemyDocumentPersistence,
)
from app.services.document_storage import FileValidationError, LocalDocumentStorage

router = APIRouter(prefix="/documents", tags=["documents"])


def get_document_storage(request: Request) -> LocalDocumentStorage:
    """Return the configured local document storage adapter."""

    settings = cast(Settings, request.app.state.settings)
    return LocalDocumentStorage.from_settings(settings)


def get_document_ingestion_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    storage: Annotated[LocalDocumentStorage, Depends(get_document_storage)],
) -> DocumentIngestionService:
    """Return the document ingestion application service."""

    return DocumentIngestionService(
        persistence=SqlAlchemyDocumentPersistence(session),
        storage=storage,
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
