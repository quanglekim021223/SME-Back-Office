from app.models import (
    AgentHandoff,
    AgentStepExecution,
    Document,
    DocumentArtifact,
    Invoice,
    InvoiceFieldEvidence,
    InvoiceLineItem,
    Membership,
    Organization,
    ProcessingRun,
    User,
    WorkflowRun,
)
from app.models.base import Base


def test_identity_tables_are_registered_in_metadata() -> None:
    assert "organizations" in Base.metadata.tables
    assert "users" in Base.metadata.tables
    assert "memberships" in Base.metadata.tables


def test_organization_model_columns() -> None:
    columns = Organization.__table__.c

    assert "id" in columns
    assert "name" in columns
    assert columns["slug"].unique is True
    assert columns["slug"].index is True
    assert "created_at" in columns
    assert "updated_at" in columns


def test_user_model_columns() -> None:
    columns = User.__table__.c

    assert "id" in columns
    assert columns["email"].unique is True
    assert columns["email"].index is True
    assert "display_name" in columns
    assert "created_at" in columns
    assert "updated_at" in columns


def test_membership_is_tenant_owned() -> None:
    columns = Membership.__table__.c
    tenant_id = columns["tenant_id"]

    assert tenant_id.index is True
    assert tenant_id.nullable is False
    assert {
        foreign_key.column.table.name for foreign_key in tenant_id.foreign_keys
    } == {"organizations"}


def test_membership_has_unique_tenant_user_constraint() -> None:
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in Membership.__table__.constraints
        if constraint.name is not None
    }

    assert constraints["uq_memberships_tenant_user"] == {"tenant_id", "user_id"}


def test_current_tenant_owned_tables_have_tenant_id() -> None:
    tenant_owned_tables = [
        Membership.__table__,
        Document.__table__,
        DocumentArtifact.__table__,
        ProcessingRun.__table__,
        WorkflowRun.__table__,
        AgentStepExecution.__table__,
        AgentHandoff.__table__,
        Invoice.__table__,
        InvoiceLineItem.__table__,
        InvoiceFieldEvidence.__table__,
    ]

    for table in tenant_owned_tables:
        assert "tenant_id" in table.c
        assert table.c["tenant_id"].nullable is False
