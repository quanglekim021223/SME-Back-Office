"""Document storage adapters, hashing, and upload validation services."""

from __future__ import annotations

import asyncio
import os
import re
import tempfile
from collections.abc import AsyncGenerator, Collection
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID

from app.core.config import DocumentStorageProvider, Settings


class FileValidationError(ValueError):
    """Raised when an uploaded file violates ingestion safety policy."""

    def __init__(self, code: str, detail: str) -> None:
        self.code = code
        self.detail = detail
        super().__init__(detail)


@dataclass(frozen=True, slots=True)
class StoredFile:
    """Metadata returned after storing an uploaded file."""

    object_key: str
    storage_uri: str
    path: Path | None
    filename: str
    media_type: str
    size_bytes: int
    content_hash: str


def compute_content_hash(content: bytes) -> str:
    """Return the SHA-256 hex digest for uploaded file bytes."""

    return sha256(content).hexdigest()


def normalize_media_type(media_type: str) -> str:
    """Normalize a MIME type and strip optional charset parameters."""

    return media_type.split(";", maxsplit=1)[0].strip().lower()


def validate_file_size(size_bytes: int, max_size_bytes: int) -> None:
    """Validate an uploaded file size against ingestion limits."""

    if size_bytes <= 0:
        raise FileValidationError(
            code="EMPTY_FILE",
            detail="Uploaded file must not be empty.",
        )

    if size_bytes > max_size_bytes:
        raise FileValidationError(
            code="FILE_TOO_LARGE",
            detail=(
                f"Uploaded file size {size_bytes} bytes exceeds the "
                f"{max_size_bytes} byte limit."
            ),
        )


def validate_mime_type(
    media_type: str,
    allowed_mime_types: Collection[str],
) -> str:
    """Validate and return a normalized MIME type."""

    normalized_media_type = normalize_media_type(media_type)
    normalized_allowed_types = {
        normalize_media_type(allowed_type) for allowed_type in allowed_mime_types
    }

    if normalized_media_type not in normalized_allowed_types:
        raise FileValidationError(
            code="UNSUPPORTED_MIME_TYPE",
            detail=f"Unsupported MIME type: {media_type}.",
        )

    return normalized_media_type


def sanitize_filename(filename: str) -> str:
    """Return a filesystem-safe basename for an uploaded filename."""

    basename = Path(filename).name.strip()
    sanitized = re.sub(r"[^A-Za-z0-9._-]+", "_", basename).strip("._")
    return sanitized or "upload"


class DocumentStorage(Protocol):
    """Storage boundary shared by HTTP uploads and background workers."""

    max_size_bytes: int
    allowed_mime_types: frozenset[str]

    async def store(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        media_type: str,
    ) -> StoredFile:
        """Validate and store a new original document."""

    async def read(self, storage_uri: str) -> bytes:
        """Read an original document for an authorized download response."""

    def materialize(self, storage_uri: str) -> AbstractAsyncContextManager[Path]:
        """Yield a local file path usable by OCR and CSV parsing code."""


class LocalDocumentStorage:
    """Filesystem-backed document storage adapter for local development."""

    def __init__(
        self,
        root_path: Path | str,
        max_size_bytes: int,
        allowed_mime_types: Collection[str],
    ) -> None:
        self.root_path = Path(root_path)
        self.max_size_bytes = max_size_bytes
        self.allowed_mime_types = frozenset(allowed_mime_types)

    @classmethod
    def from_settings(cls, settings: Settings) -> LocalDocumentStorage:
        """Build local storage using application settings."""

        return cls(
            root_path=settings.upload_storage_root,
            max_size_bytes=settings.upload_max_size_bytes,
            allowed_mime_types=settings.upload_allowed_mime_types,
        )

    async def store(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        media_type: str,
    ) -> StoredFile:
        """Validate and persist uploaded content to the local filesystem."""

        size_bytes = len(content)
        validate_file_size(size_bytes, self.max_size_bytes)
        normalized_media_type = validate_mime_type(
            media_type,
            self.allowed_mime_types,
        )

        safe_filename = sanitize_filename(filename)
        content_hash = compute_content_hash(content)
        object_key = (
            f"tenants/{tenant_id}/documents/{document_id}/original/{safe_filename}"
        )
        target_path = self.root_path / object_key

        await asyncio.to_thread(self._write_file, target_path, content)

        return StoredFile(
            object_key=object_key,
            storage_uri=f"local://{object_key}",
            path=target_path,
            filename=safe_filename,
            media_type=normalized_media_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
        )

    async def read(self, storage_uri: str) -> bytes:
        """Read a local object after validating its storage URI."""

        path = self._path_for_storage_uri(storage_uri)
        return await asyncio.to_thread(path.read_bytes)

    @asynccontextmanager
    async def materialize(self, storage_uri: str) -> AsyncGenerator[Path]:
        """Yield the persisted local path without creating a temporary copy."""

        path = self._path_for_storage_uri(storage_uri)
        if not path.is_file():
            raise FileNotFoundError(f"Document does not exist on disk: {path}")
        yield path

    def _path_for_storage_uri(self, storage_uri: str) -> Path:
        prefix = "local://"
        if not storage_uri.startswith(prefix):
            raise ValueError("LocalDocumentStorage cannot read a non-local URI.")
        object_key = storage_uri.removeprefix(prefix)
        root_path = self.root_path.resolve()
        path = (root_path / object_key).resolve()
        if root_path not in path.parents:
            raise ValueError("Local storage URI escapes the configured upload root.")
        return path

    @staticmethod
    def _write_file(target_path: Path, content: bytes) -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.with_name(f".{target_path.name}.tmp")
        temporary_path.write_bytes(content)
        temporary_path.replace(target_path)


class AzureBlobDocumentStorage:
    """Private Azure Blob adapter that materializes files only for processing."""

    URI_SCHEME = "azureblob://"

    def __init__(
        self,
        *,
        account_url: str,
        container: str,
        max_size_bytes: int,
        allowed_mime_types: Collection[str],
        connection_string: str = "",
        blob_service_client: Any | None = None,
    ) -> None:
        self.account_url = account_url.rstrip("/")
        self.container = container
        self.max_size_bytes = max_size_bytes
        self.allowed_mime_types = frozenset(allowed_mime_types)
        self._connection_string = connection_string
        self._blob_service_client = blob_service_client

    @classmethod
    def from_settings(cls, settings: Settings) -> AzureBlobDocumentStorage:
        """Build Azure Blob storage using a local secret or managed identity."""

        if not settings.azure_storage_blob_endpoint:
            raise ValueError(
                "AZURE_STORAGE_BLOB_ENDPOINT is required when "
                "DOCUMENT_STORAGE_PROVIDER=azure_blob."
            )
        if not settings.azure_storage_container:
            raise ValueError(
                "AZURE_STORAGE_CONTAINER is required when "
                "DOCUMENT_STORAGE_PROVIDER=azure_blob."
            )
        return cls(
            account_url=settings.azure_storage_blob_endpoint,
            container=settings.azure_storage_container,
            connection_string=settings.azure_storage_connection_string,
            max_size_bytes=settings.upload_max_size_bytes,
            allowed_mime_types=settings.upload_allowed_mime_types,
        )

    async def store(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        filename: str,
        content: bytes,
        media_type: str,
    ) -> StoredFile:
        """Store an original document in the configured private container."""

        size_bytes = len(content)
        validate_file_size(size_bytes, self.max_size_bytes)
        normalized_media_type = validate_mime_type(
            media_type,
            self.allowed_mime_types,
        )
        safe_filename = sanitize_filename(filename)
        content_hash = compute_content_hash(content)
        object_key = (
            f"tenants/{tenant_id}/documents/{document_id}/original/{safe_filename}"
        )
        await asyncio.to_thread(
            self._upload,
            object_key,
            content,
            normalized_media_type,
        )
        return StoredFile(
            object_key=object_key,
            storage_uri=self._storage_uri(object_key),
            path=None,
            filename=safe_filename,
            media_type=normalized_media_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
        )

    async def read(self, storage_uri: str) -> bytes:
        """Download one private Blob for an authorized API response."""

        return await asyncio.to_thread(self._download, self._object_key(storage_uri))

    @asynccontextmanager
    async def materialize(self, storage_uri: str) -> AsyncGenerator[Path]:
        """Download a Blob to a temporary file for local-path-only providers."""

        object_key = self._object_key(storage_uri)
        suffix = Path(object_key).suffix
        file_descriptor, temporary_name = tempfile.mkstemp(
            prefix="sme-document-",
            suffix=suffix,
        )
        os.close(file_descriptor)
        temporary_path = Path(temporary_name)
        try:
            content = await asyncio.to_thread(self._download, object_key)
            await asyncio.to_thread(temporary_path.write_bytes, content)
            yield temporary_path
        finally:
            await asyncio.to_thread(temporary_path.unlink, missing_ok=True)

    def _upload(self, object_key: str, content: bytes, media_type: str) -> None:
        content_settings = self._content_settings(media_type)
        self._client().get_blob_client(
            container=self.container,
            blob=object_key,
        ).upload_blob(
            content,
            overwrite=False,
            content_settings=content_settings,
        )

    def _download(self, object_key: str) -> bytes:
        content = self._client().get_blob_client(
            container=self.container,
            blob=object_key,
        ).download_blob().readall()
        return bytes(content)

    def _client(self) -> Any:
        if self._blob_service_client is not None:
            return self._blob_service_client

        try:
            from azure.identity import DefaultAzureCredential  # noqa: I001
            from azure.storage.blob import BlobServiceClient  # noqa: I001
        except ImportError as exc:
            raise RuntimeError(
                "Azure Blob storage requires azure-identity and azure-storage-blob."
            ) from exc

        if self._connection_string:
            self._blob_service_client = BlobServiceClient.from_connection_string(
                self._connection_string
            )
        else:
            self._blob_service_client = BlobServiceClient(
                account_url=self.account_url,
                credential=DefaultAzureCredential(
                    exclude_interactive_browser_credential=True,
                ),
            )
        return self._blob_service_client

    @staticmethod
    def _content_settings(media_type: str) -> Any:
        try:
            from azure.storage.blob import ContentSettings  # noqa: I001
        except ImportError as exc:
            raise RuntimeError(
                "Azure Blob storage requires azure-storage-blob."
            ) from exc
        return ContentSettings(content_type=media_type)

    def _storage_uri(self, object_key: str) -> str:
        return f"{self.URI_SCHEME}{self.container}/{object_key}"

    def _object_key(self, storage_uri: str) -> str:
        prefix = f"{self.URI_SCHEME}{self.container}/"
        if not storage_uri.startswith(prefix):
            raise ValueError("Azure Blob URI does not belong to this container.")
        return storage_uri.removeprefix(prefix)


def build_document_storage(settings: Settings) -> DocumentStorage:
    """Select local storage for development or Azure Blob for deployed runtime."""

    if settings.document_storage_provider is DocumentStorageProvider.AZURE_BLOB:
        return AzureBlobDocumentStorage.from_settings(settings)
    return LocalDocumentStorage.from_settings(settings)
