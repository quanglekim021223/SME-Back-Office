from hashlib import sha256
from uuid import uuid4

import pytest

from app.services.document_storage import (
    AzureBlobDocumentStorage,
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


async def test_local_document_storage_persists_file_and_returns_metadata(
    tmp_path,
) -> None:
    storage = LocalDocumentStorage(
        root_path=tmp_path,
        max_size_bytes=1024,
        allowed_mime_types={"application/pdf"},
    )
    tenant_id = uuid4()
    document_id = uuid4()
    content = b"%PDF-1.4 sample"

    stored_file = await storage.store(
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


class FakeBlobClient:
    def __init__(self, content_by_key: dict[str, bytes], object_key: str) -> None:
        self.content_by_key = content_by_key
        self.object_key = object_key

    def upload_blob(self, content: bytes, **_kwargs: object) -> None:
        self.content_by_key[self.object_key] = content

    def download_blob(self) -> "FakeBlobClient":
        return self

    def readall(self) -> bytes:
        return self.content_by_key[self.object_key]


class FakeBlobServiceClient:
    def __init__(self) -> None:
        self.content_by_key: dict[str, bytes] = {}

    def get_blob_client(self, *, container: str, blob: str) -> FakeBlobClient:
        assert container == "documents"
        return FakeBlobClient(self.content_by_key, blob)


async def test_azure_blob_storage_materializes_private_blob_for_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = FakeBlobServiceClient()
    storage = AzureBlobDocumentStorage(
        account_url="https://example.blob.core.windows.net",
        container="documents",
        max_size_bytes=1024,
        allowed_mime_types={"application/pdf"},
        blob_service_client=client,
    )
    monkeypatch.setattr(storage, "_content_settings", lambda _media_type: object())
    tenant_id = uuid4()
    document_id = uuid4()
    content = b"%PDF-1.4 stored in Azure Blob"

    stored_file = await storage.store(
        tenant_id=tenant_id,
        document_id=document_id,
        filename="invoice.pdf",
        content=content,
        media_type="application/pdf",
    )

    assert stored_file.path is None
    assert stored_file.storage_uri == (
        f"azureblob://documents/{stored_file.object_key}"
    )
    assert await storage.read(stored_file.storage_uri) == content

    async with storage.materialize(stored_file.storage_uri) as temporary_path:
        assert temporary_path.read_bytes() == content
    assert not temporary_path.exists()
