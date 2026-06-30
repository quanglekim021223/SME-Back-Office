"""Local document storage, hashing, and upload validation services."""

from __future__ import annotations

import re
from collections.abc import Collection
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from app.core.config import Settings


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
    path: Path
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

    def store(
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

        target_path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = target_path.with_name(f".{target_path.name}.tmp")
        temporary_path.write_bytes(content)
        temporary_path.replace(target_path)

        return StoredFile(
            object_key=object_key,
            storage_uri=f"local://{object_key}",
            path=target_path,
            filename=safe_filename,
            media_type=normalized_media_type,
            size_bytes=size_bytes,
            content_hash=content_hash,
        )
