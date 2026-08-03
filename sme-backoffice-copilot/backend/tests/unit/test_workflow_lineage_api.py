"""Unit coverage for tenant-scoped workflow execution lineage."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers.documents import get_workflow_runtime_repository
from app.models.operations import AuditActorType, AuditEvent
from app.models.workflow import AgentHandoff, AgentStepExecution, WorkflowRun
from app.repositories.base import TenantScopedRepository
from app.repositories.workflows import WorkflowRuntimeRepository
from app.services.workflow_lineage import WorkflowLineageService


class FakeLineageRepository:
    """Small tenant-aware fake matching the lineage persistence contract."""

    def __init__(
        self,
        *,
        workflow_run: WorkflowRun,
        steps: list[AgentStepExecution],
        handoffs: list[AgentHandoff],
        audit_events: list[AuditEvent],
    ) -> None:
        self.workflow_run = workflow_run
        self.steps = steps
        self.handoffs = handoffs
        self.audit_events = audit_events
        self.calls: list[tuple[str, UUID]] = []

    async def get_latest_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
    ) -> WorkflowRun | None:
        self.calls.append(("workflow", tenant_id))
        if (
            self.workflow_run.tenant_id != tenant_id
            or self.workflow_run.document_id != document_id
        ):
            return None
        return self.workflow_run

    async def list_steps_for_run(
        self,
        *,
        tenant_id: UUID,
        workflow_run_id: UUID,
    ) -> list[AgentStepExecution]:
        self.calls.append(("steps", tenant_id))
        return [
            step
            for step in self.steps
            if step.tenant_id == tenant_id and step.workflow_run_id == workflow_run_id
        ]

    async def list_handoffs_for_run(
        self,
        *,
        tenant_id: UUID,
        workflow_run_id: UUID,
    ) -> list[AgentHandoff]:
        self.calls.append(("handoffs", tenant_id))
        return [
            handoff
            for handoff in self.handoffs
            if handoff.tenant_id == tenant_id
            and handoff.workflow_run_id == workflow_run_id
        ]

    async def list_review_audit_events_for_document(
        self,
        *,
        tenant_id: UUID,
        document_id: UUID,
        workflow_run_id: UUID,
    ) -> list[AuditEvent]:
        del document_id, workflow_run_id
        self.calls.append(("audit", tenant_id))
        return [event for event in self.audit_events if event.tenant_id == tenant_id]


def lineage_fixture() -> tuple[
    UUID,
    UUID,
    WorkflowRun,
    list[AgentStepExecution],
    list[AgentHandoff],
    list[AuditEvent],
]:
    tenant_id = uuid4()
    document_id = uuid4()
    workflow_run_id = uuid4()
    now = datetime.now(UTC)
    qa_step_id = uuid4()
    workflow_run = WorkflowRun(
        id=workflow_run_id,
        tenant_id=tenant_id,
        document_id=document_id,
        workflow_name="invoice_processing",
        workflow_version="1.0.0",
        status="completed",
        state={
            "status": "completed",
            "stage": "completed",
            "current_agent": "qa_validator",
            "retry_counts": {"totals_extractor": 1},
            "scratchpad": {"raw_ocr_text": "must not be exposed"},
            "qa_error_signals": [
                {
                    "code": "ERR_LOGIC_MATH",
                    "message": "Subtotal + Tax != Total",
                    "retryable": True,
                    "correction_target": {
                        "target_agent": "totals_extractor",
                        "field_path": "totals.total_amount",
                        "instruction": "Recalculate the total from source evidence.",
                    },
                }
            ],
        },
        created_at=now,
        updated_at=now + timedelta(seconds=4),
    )
    steps = [
        AgentStepExecution(
            id=qa_step_id,
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            agent_name="qa_validator",
            status="retrying",
            attempt=1,
            confidence="high",
            metrics={"duration_ms": 350},
            created_at=now,
            updated_at=now + timedelta(milliseconds=350),
        ),
        AgentStepExecution(
            id=uuid4(),
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            agent_name="totals_extractor",
            status="succeeded",
            attempt=2,
            confidence="medium",
            metrics={"duration_ms": 120},
            created_at=now + timedelta(milliseconds=351),
            updated_at=now + timedelta(milliseconds=471),
        ),
    ]
    handoffs = [
        AgentHandoff(
            id=uuid4(),
            tenant_id=tenant_id,
            workflow_run_id=workflow_run_id,
            source_step_execution_id=qa_step_id,
            source_agent="qa_validator",
            target_agent="totals_extractor",
            handoff_type="correction",
            schema_version="agent-handoff.v1",
            status="consumed",
            payload_ref="inline://correction",
            confidence="high",
            attempt=1,
            created_at=now + timedelta(milliseconds=350),
            updated_at=now + timedelta(milliseconds=350),
        )
    ]
    audit_events = [
        AuditEvent(
            id=uuid4(),
            tenant_id=tenant_id,
            actor_type=AuditActorType.USER.value,
            action="review_task.approved",
            resource_type="invoice",
            resource_id=uuid4(),
            occurred_at=now + timedelta(seconds=5),
            metadata_={
                "actor_subject": "reviewer@example.com",
                "comment": "Verified against the original invoice.",
            },
            created_at=now + timedelta(seconds=5),
            updated_at=now + timedelta(seconds=5),
        )
    ]
    return tenant_id, document_id, workflow_run, steps, handoffs, audit_events


def auth_headers(tenant_id: UUID) -> dict[str, str]:
    return {
        "X-Tenant-ID": str(tenant_id),
        "X-User-ID": str(uuid4()),
        "X-User-Role": "member",
    }


def test_lineage_service_builds_retry_and_human_audit_nodes() -> None:
    tenant_id, document_id, workflow_run, steps, handoffs, audit_events = (
        lineage_fixture()
    )
    repository = FakeLineageRepository(
        workflow_run=workflow_run,
        steps=steps,
        handoffs=handoffs,
        audit_events=audit_events,
    )

    lineage = asyncio.run(
        WorkflowLineageService(repository).get_for_document(
            tenant_id=tenant_id,
            document_id=document_id,
        )
    )

    assert lineage.total_latency_ms == 470
    assert lineage.steps[0].correction_signal is not None
    assert lineage.steps[0].correction_signal.code == "ERR_LOGIC_MATH"
    assert lineage.steps[0].correction_signal.target_agent == "totals_extractor"
    assert lineage.handoffs[0].correction_signal is not None
    assert lineage.audit_history[0].actor_name == "reviewer@example.com"
    assert "scratchpad" not in lineage.workflow_state
    assert {call[0] for call in repository.calls} == {
        "workflow",
        "steps",
        "handoffs",
        "audit",
    }


def test_lineage_endpoint_returns_structured_payload(
    app: FastAPI,
    client: TestClient,
) -> None:
    tenant_id, document_id, workflow_run, steps, handoffs, audit_events = (
        lineage_fixture()
    )
    repository = FakeLineageRepository(
        workflow_run=workflow_run,
        steps=steps,
        handoffs=handoffs,
        audit_events=audit_events,
    )
    app.dependency_overrides[get_workflow_runtime_repository] = lambda: repository

    response = client.get(
        f"/api/v1/documents/{document_id}/lineage",
        headers=auth_headers(tenant_id),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["document_id"] == str(document_id)
    assert payload["workflow_run_id"] == str(workflow_run.id)
    assert payload["total_latency_ms"] == 470
    assert payload["steps"][0]["correction_signal"]["code"] == "ERR_LOGIC_MATH"
    assert payload["audit_history"][0]["action"] == "review_task.approved"


def test_lineage_endpoint_hides_other_tenant_workflow(
    app: FastAPI,
    client: TestClient,
) -> None:
    owner_tenant_id, document_id, workflow_run, steps, handoffs, audit_events = (
        lineage_fixture()
    )
    repository = FakeLineageRepository(
        workflow_run=workflow_run,
        steps=steps,
        handoffs=handoffs,
        audit_events=audit_events,
    )
    app.dependency_overrides[get_workflow_runtime_repository] = lambda: repository

    response = client.get(
        f"/api/v1/documents/{document_id}/lineage",
        headers=auth_headers(uuid4()),
    )

    assert owner_tenant_id != UUID(response.request.headers["X-Tenant-ID"])
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "workflow_lineage_not_found"


def test_workflow_repository_is_tenant_scoped() -> None:
    assert issubclass(WorkflowRuntimeRepository, TenantScopedRepository)
