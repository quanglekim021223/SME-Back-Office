from app.models import (
    AgentDefinition,
    AgentHandoff,
    AgentStepExecution,
    AgentStepStatus,
    HandoffStatus,
    WorkflowRun,
    WorkflowRunStatus,
)
from app.models.base import Base


def test_workflow_tables_are_registered_in_metadata() -> None:
    assert "workflow_runs" in Base.metadata.tables
    assert "agent_definitions" in Base.metadata.tables
    assert "agent_step_executions" in Base.metadata.tables
    assert "agent_handoffs" in Base.metadata.tables


def test_workflow_run_columns_and_defaults() -> None:
    columns = WorkflowRun.__table__.c

    assert "tenant_id" in columns
    assert "document_id" in columns
    assert "processing_run_id" in columns
    assert "workflow_name" in columns
    assert "workflow_version" in columns
    assert columns["status"].default is not None
    assert columns["status"].default.arg == WorkflowRunStatus.QUEUED.value
    assert "state" in columns
    assert "correlation_id" in columns


def test_agent_definition_has_versioned_registry_constraint() -> None:
    columns = AgentDefinition.__table__.c
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in AgentDefinition.__table__.constraints
        if constraint.name is not None
    }

    assert "agent_name" in columns
    assert "agent_version" in columns
    assert "allowed_tools" in columns
    assert "retry_policy" in columns
    assert constraints["uq_agent_definitions_name_version"] == {
        "agent_name",
        "agent_version",
    }


def test_agent_step_execution_links_to_workflow_and_agent_definition() -> None:
    columns = AgentStepExecution.__table__.c

    assert "tenant_id" in columns
    assert columns["workflow_run_id"].index is True
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["workflow_run_id"].foreign_keys
    } == {"workflow_runs"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["agent_definition_id"].foreign_keys
    } == {"agent_definitions"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == AgentStepStatus.SCHEDULED.value
    assert "attempt" in columns
    assert "metrics" in columns


def test_agent_handoff_links_to_workflow_and_source_step() -> None:
    columns = AgentHandoff.__table__.c

    assert "tenant_id" in columns
    assert columns["workflow_run_id"].index is True
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["workflow_run_id"].foreign_keys
    } == {"workflow_runs"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["source_step_execution_id"].foreign_keys
    } == {"agent_step_executions"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == HandoffStatus.CREATED.value
    assert "payload_ref" in columns
    assert "evidence_refs" in columns
    assert "policy_flags" in columns


def test_workflow_enums_expose_stable_values() -> None:
    assert WorkflowRunStatus.REVIEW_REQUIRED.value == "review_required"
    assert WorkflowRunStatus.RETRYING.value == "retrying"
    assert WorkflowRunStatus.LOST.value == "lost"
    assert WorkflowRunStatus.DEAD_LETTERED.value == "dead_lettered"
    assert AgentStepStatus.RETRYING.value == "retrying"
    assert HandoffStatus.SUPERSEDED.value == "superseded"
