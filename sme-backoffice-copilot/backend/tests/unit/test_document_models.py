from app.models import (
    ArtifactType,
    Document,
    DocumentArtifact,
    DocumentStatus,
    DocumentType,
    ProcessingRun,
    ProcessingRunStatus,
)
from app.models.base import Base


def test_document_tables_are_registered_in_metadata() -> None:
    assert "documents" in Base.metadata.tables
    assert "document_artifacts" in Base.metadata.tables
    assert "processing_runs" in Base.metadata.tables


def test_document_model_columns_and_defaults() -> None:
    columns = Document.__table__.c

    assert "tenant_id" in columns
    assert "document_type" in columns
    assert columns["status"].default is not None
    assert columns["status"].default.arg == DocumentStatus.UPLOADED.value
    assert "original_filename" in columns
    assert "mime_type" in columns
    assert "size_bytes" in columns
    assert "content_hash" in columns
    assert "created_at" in columns
    assert "updated_at" in columns


def test_document_has_unique_tenant_content_hash_constraint() -> None:
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in Document.__table__.constraints
        if constraint.name is not None
    }

    assert constraints["uq_documents_tenant_hash"] == {"tenant_id", "content_hash"}


def test_document_artifact_links_to_document() -> None:
    columns = DocumentArtifact.__table__.c
    document_id = columns["document_id"]

    assert "tenant_id" in columns
    assert document_id.index is True
    assert document_id.nullable is False
    assert {
        foreign_key.column.table.name for foreign_key in document_id.foreign_keys
    } == {"documents"}
    assert "storage_uri" in columns
    assert "metadata" in columns


def test_processing_run_links_to_document() -> None:
    columns = ProcessingRun.__table__.c
    document_id = columns["document_id"]

    assert "tenant_id" in columns
    assert document_id.index is True
    assert document_id.nullable is False
    assert {
        foreign_key.column.table.name for foreign_key in document_id.foreign_keys
    } == {"documents"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == ProcessingRunStatus.QUEUED.value
    assert "workflow_name" in columns
    assert "workflow_version" in columns
    assert "metrics" in columns


def test_document_enums_expose_stable_values() -> None:
    assert DocumentType.INVOICE.value == "invoice"
    assert ArtifactType.ORIGINAL.value == "original"
    assert ProcessingRunStatus.SUCCEEDED.value == "succeeded"
