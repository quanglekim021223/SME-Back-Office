from pathlib import Path

import pytest

from app.core.config import Settings
from app.dev_reset import (
    DEV_RESET_DELETE_ORDER,
    assert_safe_upload_reset_path,
    clear_upload_storage,
    ensure_dev_reset_allowed,
)


def test_dev_reset_allows_local_environment() -> None:
    ensure_dev_reset_allowed(settings=Settings(app_env="local"))


def test_dev_reset_rejects_non_local_environment() -> None:
    with pytest.raises(RuntimeError, match="Refusing to reset data"):
        ensure_dev_reset_allowed(settings=Settings(app_env="production"))


def test_dev_reset_delete_order_keeps_documents_last() -> None:
    table_names = [spec.name for spec in DEV_RESET_DELETE_ORDER]

    assert table_names.index("review_tasks") < table_names.index("documents")
    assert table_names.index("invoices") < table_names.index("documents")
    assert table_names.index("document_artifacts") < table_names.index("documents")


def test_dev_reset_path_guard_rejects_path_outside_upload_root() -> None:
    with pytest.raises(RuntimeError, match="outside upload root"):
        assert_safe_upload_reset_path(
            root_path=Path("/tmp/sme/uploads"),
            target_path=Path("/tmp/other"),
        )


def test_clear_upload_storage_preserves_gitkeep_for_full_reset(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitkeep").touch()
    (tmp_path / "tenants" / "tenant-a").mkdir(parents=True)
    (tmp_path / "tenants" / "tenant-a" / "invoice.pdf").write_bytes(b"invoice")

    removed_path = clear_upload_storage(
        settings=Settings(upload_storage_root=str(tmp_path)),
        tenant_id=None,
    )

    assert removed_path == tmp_path
    assert (tmp_path / ".gitkeep").exists()
    assert not (tmp_path / "tenants").exists()
