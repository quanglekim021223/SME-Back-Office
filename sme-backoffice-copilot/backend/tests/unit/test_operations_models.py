from app.models import (
    AuditActorType,
    AuditEvent,
    AuditEventSeverity,
    Insight,
    InsightSeverity,
    InsightStatus,
    InsightType,
    ReviewTargetType,
    ReviewTask,
    ReviewTaskPriority,
    ReviewTaskStatus,
    ReviewTaskType,
)
from app.models.base import Base


def test_operations_tables_are_registered_in_metadata() -> None:
    assert "review_tasks" in Base.metadata.tables
    assert "insights" in Base.metadata.tables
    assert "audit_events" in Base.metadata.tables


def test_review_task_columns_defaults_and_user_links() -> None:
    columns = ReviewTask.__table__.c

    assert "tenant_id" in columns
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["assigned_user_id"].foreign_keys
    } == {"users"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["resolved_by_user_id"].foreign_keys
    } == {"users"}
    assert columns["task_type"].default is not None
    assert columns["task_type"].default.arg == ReviewTaskType.OTHER.value
    assert columns["target_type"].default is not None
    assert columns["target_type"].default.arg == ReviewTargetType.OTHER.value
    assert columns["status"].default is not None
    assert columns["status"].default.arg == ReviewTaskStatus.OPEN.value
    assert columns["priority"].default is not None
    assert columns["priority"].default.arg == ReviewTaskPriority.NORMAL.value
    assert "title" in columns
    assert columns["title"].nullable is False
    assert "description" in columns
    assert "reason_code" in columns
    assert "due_at" in columns
    assert "resolved_at" in columns
    assert "evidence_refs" in columns
    assert "metadata" in columns


def test_review_task_links_to_reviewable_resources() -> None:
    columns = ReviewTask.__table__.c

    assert {
        foreign_key.column.table.name
        for foreign_key in columns["workflow_run_id"].foreign_keys
    } == {"workflow_runs"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["document_id"].foreign_keys
    } == {"documents"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["invoice_id"].foreign_keys
    } == {"invoices"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["transaction_id"].foreign_keys
    } == {"transactions"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["classification_proposal_id"].foreign_keys
    } == {"classification_proposals"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["reconciliation_id"].foreign_keys
    } == {"reconciliations"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["insight_id"].foreign_keys
    } == {"insights"}


def test_insight_columns_defaults_and_version_links() -> None:
    columns = Insight.__table__.c

    assert "tenant_id" in columns
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["source_workflow_run_id"].foreign_keys
    } == {"workflow_runs"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["supersedes_insight_id"].foreign_keys
    } == {"insights"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == InsightStatus.GENERATED.value
    assert columns["insight_type"].default is not None
    assert columns["insight_type"].default.arg == InsightType.OTHER.value
    assert columns["severity"].default is not None
    assert columns["severity"].default.arg == InsightSeverity.INFO.value
    assert "title" in columns
    assert columns["title"].nullable is False
    assert "summary" in columns
    assert columns["summary"].nullable is False
    assert "recommendation" in columns
    assert "period_start" in columns
    assert "period_end" in columns
    assert "estimated_impact_amount" in columns
    assert "evidence_refs" in columns
    assert "metrics" in columns
    assert "metadata" in columns


def test_audit_event_columns_defaults_and_actor_link() -> None:
    columns = AuditEvent.__table__.c

    assert "tenant_id" in columns
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["actor_user_id"].foreign_keys
    } == {"users"}
    assert "occurred_at" in columns
    assert columns["occurred_at"].default is not None
    assert columns["actor_type"].default is not None
    assert columns["actor_type"].default.arg == AuditActorType.SYSTEM.value
    assert columns["severity"].default is not None
    assert columns["severity"].default.arg == AuditEventSeverity.INFO.value
    assert "action" in columns
    assert columns["action"].nullable is False
    assert "resource_type" in columns
    assert "resource_id" in columns
    assert "correlation_id" in columns
    assert "request_id" in columns
    assert "ip_address" in columns
    assert "user_agent" in columns
    assert "before_state" in columns
    assert "after_state" in columns
    assert "metadata" in columns


def test_operations_enums_expose_stable_values() -> None:
    assert ReviewTaskType.RECONCILIATION.value == "reconciliation"
    assert ReviewTargetType.CLASSIFICATION_PROPOSAL.value == "classification_proposal"
    assert ReviewTaskStatus.RESOLVED.value == "resolved"
    assert InsightType.CASHFLOW.value == "cashflow"
    assert InsightSeverity.CRITICAL.value == "critical"
    assert AuditActorType.AGENT.value == "agent"
    assert AuditEventSeverity.WARNING.value == "warning"
