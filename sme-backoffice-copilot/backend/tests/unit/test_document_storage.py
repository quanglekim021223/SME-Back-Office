from hashlib import sha256
from uuid import uuid4

import pytest

from app.services.document_storage import (
    FileValidationError,
    LocalDocumentStorage,
    compute_content_hash,
    sanitize_filename,
    validate_file_size,
    validate_mime_type,
)


def test_compute_content_hash_returns_sha256_hex_digest() -> None:
    content = b"invoice bytes"

    assert compute_content_hash(content) == sha256(content).hexdigest()


def test_validate_file_size_rejects_empty_files() -> None:
    with pytest.raises(FileValidationError) as exc_info:
        validate_file_size(size_bytes=0, max_size_bytes=10)

    assert exc_info.value.code == "EMPTY_FILE"


def test_validate_file_size_rejects_files_above_limit() -> None:
    with pytest.raises(FileValidationError) as exc_info:
        validate_file_size(size_bytes=11, max_size_bytes=10)

    assert exc_info.value.code == "FILE_TOO_LARGE"


def test_validate_mime_type_accepts_allowed_type_with_charset() -> None:
    normalized_media_type = validate_mime_type(
        media_type="text/csv; charset=utf-8",
        allowed_mime_types={"text/csv"},
    )

    assert normalized_media_type == "text/csv"


def test_validate_mime_type_rejects_unsupported_type() -> None:
    with pytest.raises(FileValidationError) as exc_info:
        validate_mime_type(
            media_type="application/x-msdownload",
            allowed_mime_types={"application/pdf"},
        )

    assert exc_info.value.code == "UNSUPPORTED_MIME_TYPE"


def test_sanitize_filename_removes_paths_and_unsafe_characters() -> None:
    assert (
        sanitize_filename("../../Invoice June 2026 #1.pdf") == "Invoice_June_2026_1.pdf"
    )


def test_local_document_storage_persists_file_and_returns_metadata(tmp_path) -> None:
    storage = LocalDocumentStorage(
        root_path=tmp_path,
        max_size_bytes=1024,
        allowed_mime_types={"application/pdf"},
    )
    tenant_id = uuid4()
    document_id = uuid4()
    content = b"%PDF-1.4 sample"

    stored_file = storage.store(
        tenant_id=tenant_id,
        document_id=document_id,
        filename="invoice.pdf",
        content=content,
        media_type="application/pdf",
    )

    assert stored_file.path.read_bytes() == content
    assert stored_file.filename == "invoice.pdf"
    assert stored_file.media_type == "application/pdf"
    assert stored_file.size_bytes == len(content)
    assert stored_file.content_hash == sha256(content).hexdigest()
    assert stored_file.object_key == (
        f"tenants/{tenant_id}/documents/{document_id}/original/invoice.pdf"
    )
    assert stored_file.storage_uri == f"local://{stored_file.object_key}"
