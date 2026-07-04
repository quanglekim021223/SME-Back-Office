"""Reset local development upload/workflow data.

This command is intentionally scoped to local development. It clears uploaded
documents, generated invoice proposals, workflow runtime rows, review tasks,
audit rows, and local uploaded files while preserving demo organizations,
users, memberships, categories, and other identity seed data.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from sqlalchemy import delete
from sqlalchemy.engine import CursorResult

from app.core.config import Settings, get_settings
from app.core.db import async_session_factory
from app.models import (
    AgentHandoff,
    AgentStepExecution,
    AuditEvent,
    ClassificationProposal,
    Document,
    DocumentArtifact,
    Insight,
    Invoice,
    InvoiceFieldEvidence,
    InvoiceLineItem,
    ProcessingRun,
    Reconciliation,
    ReconciliationAllocation,
    ReviewTask,
    StatementImport,
    Transaction,
    WorkflowRun,
)
from app.models.base import Base

ALLOWED_DEV_ENVS = frozenset({"local", "dev", "development", "test"})


@dataclass(frozen=True, slots=True)
class ResetModelSpec:
    """One ORM model cleared by the dev reset command."""

    name: str
    model: type[Base]


DEV_RESET_DELETE_ORDER: tuple[ResetModelSpec, ...] = (
    ResetModelSpec("review_tasks", ReviewTask),
    ResetModelSpec("audit_events", AuditEvent),
    ResetModelSpec("invoice_field_evidence", InvoiceFieldEvidence),
    ResetModelSpec("classification_proposals", ClassificationProposal),
    ResetModelSpec("reconciliation_allocations", ReconciliationAllocation),
    ResetModelSpec("reconciliations", Reconciliation),
    ResetModelSpec("invoice_line_items", InvoiceLineItem),
    ResetModelSpec("invoices", Invoice),
    ResetModelSpec("insights", Insight),
    ResetModelSpec("agent_handoffs", AgentHandoff),
    ResetModelSpec("agent_step_executions", AgentStepExecution),
    ResetModelSpec("workflow_runs", WorkflowRun),
    ResetModelSpec("transactions", Transaction),
    ResetModelSpec("statement_imports", StatementImport),
    ResetModelSpec("processing_runs", ProcessingRun),
    ResetModelSpec("document_artifacts", DocumentArtifact),
    ResetModelSpec("documents", Document),
)


@dataclass(frozen=True, slots=True)
class DevResetResult:
    """Summary returned by the dev reset command."""

    deleted_rows_by_table: dict[str, int]
    removed_storage_path: Path | None


def ensure_dev_reset_allowed(
    *,
    settings: Settings,
    force_env: bool = False,
) -> None:
    """Raise unless the command is running in a local/dev/test environment."""

    if force_env:
        return
    normalized_env = settings.app_env.lower().strip()
    if normalized_env not in ALLOWED_DEV_ENVS:
        raise RuntimeError(
            "Refusing to reset data because APP_ENV is "
            f"'{settings.app_env}'. Allowed local envs: "
            f"{', '.join(sorted(ALLOWED_DEV_ENVS))}."
        )


async def reset_dev_data(
    *,
    tenant_id: UUID | None = None,
    keep_files: bool = False,
    force_env: bool = False,
) -> DevResetResult:
    """Delete local dev upload/workflow data and optionally local uploaded files."""

    settings = get_settings()
    ensure_dev_reset_allowed(settings=settings, force_env=force_env)

    deleted_rows_by_table: dict[str, int] = {}
    async with async_session_factory() as session:
        for spec in DEV_RESET_DELETE_ORDER:
            statement = delete(spec.model)
            if tenant_id is not None:
                statement = statement.where(
                    cast(Any, spec.model).tenant_id == tenant_id
                )
            result = cast(CursorResult[Any], await session.execute(statement))
            deleted_rows_by_table[spec.name] = max(result.rowcount or 0, 0)
        await session.commit()

    removed_storage_path = None
    if not keep_files:
        removed_storage_path = clear_upload_storage(
            settings=settings,
            tenant_id=tenant_id,
        )

    return DevResetResult(
        deleted_rows_by_table=deleted_rows_by_table,
        removed_storage_path=removed_storage_path,
    )


def clear_upload_storage(
    *,
    settings: Settings,
    tenant_id: UUID | None,
) -> Path | None:
    """Remove local uploaded files for one tenant or all tenants."""

    root_path = resolve_upload_storage_root(settings)
    target_path = root_path / "tenants" / str(tenant_id) if tenant_id else root_path
    if not target_path.exists():
        return None

    assert_safe_upload_reset_path(root_path=root_path, target_path=target_path)
    root_path.mkdir(parents=True, exist_ok=True)
    if tenant_id is None:
        for child_path in target_path.iterdir():
            if child_path.name == ".gitkeep":
                continue
            remove_storage_path(child_path)
        (root_path / ".gitkeep").touch(exist_ok=True)
    else:
        remove_storage_path(target_path)
    return target_path


def remove_storage_path(path: Path) -> None:
    """Remove one storage file or directory."""

    if path.is_dir():
        shutil.rmtree(path)
    else:
        path.unlink()


def resolve_upload_storage_root(settings: Settings) -> Path:
    """Resolve upload storage root relative to the current backend working dir."""

    path = Path(settings.upload_storage_root)
    return path if path.is_absolute() else (Path.cwd() / path).resolve()


def assert_safe_upload_reset_path(*, root_path: Path, target_path: Path) -> None:
    """Guard against accidentally deleting a broad filesystem path."""

    resolved_root = root_path.resolve()
    resolved_target = target_path.resolve()
    if resolved_target == Path("/"):
        raise RuntimeError("Refusing to remove filesystem root.")
    if len(resolved_target.parts) < 4:
        raise RuntimeError(f"Refusing to remove broad path: {resolved_target}.")
    if not resolved_target.is_relative_to(resolved_root):
        raise RuntimeError(
            f"Refusing to remove path outside upload root: {resolved_target}."
        )


def build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI arguments for the dev reset command."""

    parser = argparse.ArgumentParser(
        description="Reset local development upload/workflow data.",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Confirm destructive local reset.",
    )
    parser.add_argument(
        "--tenant-id",
        type=UUID,
        default=None,
        help="Optionally reset only one tenant UUID.",
    )
    parser.add_argument(
        "--keep-files",
        action="store_true",
        help="Delete database rows but keep local uploaded files.",
    )
    parser.add_argument(
        "--force-env",
        action="store_true",
        help="Bypass APP_ENV safety check. Use only for disposable local DBs.",
    )
    return parser


def print_result(result: DevResetResult) -> None:
    """Print a compact human-readable reset summary."""

    print("Local dev reset completed.")
    print("Deleted rows:")
    for table_name, row_count in result.deleted_rows_by_table.items():
        print(f"  - {table_name}: {row_count}")
    if result.removed_storage_path is None:
        print("Removed files: none")
    else:
        print(f"Removed files: {result.removed_storage_path}")


def main() -> int:
    """Run the local development reset command."""

    parser = build_arg_parser()
    args = parser.parse_args()
    if not args.yes:
        parser.error("Refusing to reset without --yes.")

    result = asyncio.run(
        reset_dev_data(
            tenant_id=cast(UUID | None, args.tenant_id),
            keep_files=cast(bool, args.keep_files),
            force_env=cast(bool, args.force_env),
        )
    )
    print_result(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
