"""Local LangGraph debug command for one document workflow run."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Sequence
from pathlib import Path
from uuid import UUID

from app.core.config import get_settings
from app.core.db import async_session_factory
from app.models.document import ArtifactType, Document, DocumentArtifact
from app.observability.tracing import InMemoryTraceProvider, RedactingTraceProvider
from app.providers import (
    ProviderRuntime,
    build_llm_provider_from_settings,
    build_ocr_provider_from_settings,
    build_provider_routing_config_from_settings,
)
from app.workflows.agents import AgentExecutionContext
from app.workflows.contracts import WorkflowArtifactRef, WorkflowState
from app.workflows.invoice_extraction import create_total_amount_correction_signal
from app.workflows.langgraph_adapter import LangGraphWorkflowAdapter
from app.workflows.replay import (
    WORKFLOW_REPLAY_NAME,
    WORKFLOW_REPLAY_VERSION,
    InMemoryWorkflowRuntimePersistence,
    create_replay_state,
)
from app.workflows.runtime import WorkflowRuntimeService


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the local LangGraph invoice workflow and print a redacted debug trace."
        )
    )
    parser.add_argument("--document-id", type=UUID, required=True)
    parser.add_argument("--tenant-id", type=UUID, default=None)
    parser.add_argument("--max-retries", type=int, default=3)
    parser.add_argument(
        "--use-uploaded-document",
        action="store_true",
        help="Load original artifact metadata from the configured database.",
    )
    parser.add_argument(
        "--inject-correction",
        action="store_true",
        help="Inject a QA correction signal to exercise retry routing.",
    )
    return parser


async def run_debug(args: argparse.Namespace) -> dict[str, object]:
    """Run a local graph workflow and return a JSON-safe trace summary."""

    settings = get_settings()
    routing = build_provider_routing_config_from_settings(settings)
    provider_runtime = ProviderRuntime(routing)
    llm_provider = build_llm_provider_from_settings(settings)
    ocr_provider = build_ocr_provider_from_settings(settings)
    memory_trace_provider = InMemoryTraceProvider()
    trace_provider = RedactingTraceProvider(
        memory_trace_provider,
        max_payload_chars=settings.tracing_max_payload_chars,
    )

    persistence = InMemoryWorkflowRuntimePersistence()
    runtime = WorkflowRuntimeService(persistence)
    state = (
        await _load_uploaded_document_state(
            document_id=args.document_id,
            tenant_id=args.tenant_id,
            max_retries=args.max_retries,
            upload_storage_root=settings.upload_storage_root,
        )
        if args.use_uploaded_document
        else create_replay_state(
            tenant_id=args.tenant_id,
            document_id=args.document_id,
            max_retries=args.max_retries,
        )
    )
    if args.inject_correction:
        state.qa_error_signals.append(
            create_total_amount_correction_signal(
                expected_value="110.00",
                observed_value="120.00",
                evidence_refs=["debug:evidence"],
            )
        )

    workflow_run = runtime.start_workflow(
        state=state,
        workflow_name=WORKFLOW_REPLAY_NAME,
        workflow_version=WORKFLOW_REPLAY_VERSION,
        correlation_id=f"langgraph-debug-{args.document_id}",
    )
    context = AgentExecutionContext(
        tenant_id=state.tenant_id,
        document_id=state.document_id,
        workflow_run_id=workflow_run.id,
        max_retries=state.max_retries,
        provider_runtime=provider_runtime,
        llm_provider=llm_provider,
        ocr_provider=ocr_provider,
        trace_provider=trace_provider,
    )

    result = await LangGraphWorkflowAdapter(runtime).run_invoice_extraction_until_qa(
        state=state,
        workflow_run=workflow_run,
        context=context,
    )

    return {
        "workflow_run_id": str(result.workflow_run.id),
        "source": "uploaded_document" if args.use_uploaded_document else "replay",
        "tenant_id": str(result.state.tenant_id),
        "document_id": str(result.state.document_id),
        "used_langgraph": result.used_langgraph,
        "workflow_status": result.state.status.value,
        "stage": result.state.stage.value,
        "current_agent": result.state.current_agent,
        "step_count": len(result.step_executions),
        "handoff_count": len(result.handoffs),
        "retry_decisions": [
            {
                "agent_name": decision.agent_name,
                "retry_count": decision.retry_count,
                "max_retries": decision.max_retries,
                "retry_allowed": decision.retry_allowed,
                "workflow_status": decision.workflow_status.value,
                "error_code": decision.error_code,
            }
            for decision in result.retry_decisions
        ],
        "steps": [
            {
                "agent": step.agent_name,
                "status": step.status,
                "error_code": step.error_code,
            }
            for step in result.step_executions
        ],
        "handoffs": [
            {
                "source": handoff.source_agent,
                "target": handoff.target_agent,
                "type": handoff.handoff_type,
                "status": handoff.status,
            }
            for handoff in result.handoffs
        ],
        "checkpoints": result.checkpoints,
        "trace_events": [
            {
                "name": event.name,
                "correlation_id": event.correlation_id,
                "payload": dict(event.payload),
            }
            for event in memory_trace_provider.events
        ],
    }


async def _load_uploaded_document_state(
    *,
    document_id: UUID,
    tenant_id: UUID | None,
    max_retries: int,
    upload_storage_root: str,
) -> WorkflowState:
    """Build workflow state from one uploaded document and its original artifact."""

    from sqlalchemy import select

    statement = (
        select(Document, DocumentArtifact)
        .join(DocumentArtifact, DocumentArtifact.document_id == Document.id)
        .where(
            Document.id == document_id,
            DocumentArtifact.artifact_type == ArtifactType.ORIGINAL.value,
        )
    )
    if tenant_id is not None:
        statement = statement.where(Document.tenant_id == tenant_id)

    async with async_session_factory() as session:
        result = await session.execute(statement)
        row = result.first()

    if row is None:
        raise SystemExit(f"No uploaded document artifact found for {document_id}.")

    document, artifact = row
    metadata = dict(artifact.metadata_ or {})
    object_key = str(metadata.get("object_key") or "")
    if not object_key and artifact.storage_uri.startswith("local://"):
        object_key = artifact.storage_uri.removeprefix("local://")

    local_path = str(Path(upload_storage_root) / object_key) if object_key else None
    if local_path is not None:
        metadata["local_path"] = local_path

    return WorkflowState(
        tenant_id=document.tenant_id,
        document_id=document.id,
        document_type=document.document_type,
        max_retries=max_retries,
        artifacts={
            "original": WorkflowArtifactRef(
                artifact_type=artifact.artifact_type,
                uri=artifact.storage_uri,
                media_type=artifact.media_type,
                content_hash=artifact.content_hash,
                metadata=metadata,
            )
        },
        policy_flags={"document_status": document.status},
    )


def main(argv: Sequence[str] | None = None) -> None:
    """CLI entry point."""

    args = _build_parser().parse_args(argv)
    summary = asyncio.run(run_debug(args))
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
