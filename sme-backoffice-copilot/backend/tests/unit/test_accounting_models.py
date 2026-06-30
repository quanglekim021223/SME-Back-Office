from app.models import (
    Category,
    CategoryType,
    ClassificationProposal,
    ClassificationProposalStatus,
    ClassificationTargetType,
    Reconciliation,
    ReconciliationAllocation,
    ReconciliationAllocationStatus,
    ReconciliationMatchType,
    ReconciliationStatus,
)
from app.models.base import Base


def test_accounting_tables_are_registered_in_metadata() -> None:
    assert "categories" in Base.metadata.tables
    assert "classification_proposals" in Base.metadata.tables
    assert "reconciliations" in Base.metadata.tables
    assert "reconciliation_allocations" in Base.metadata.tables


def test_category_columns_defaults_and_unique_slug_constraint() -> None:
    columns = Category.__table__.c
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in Category.__table__.constraints
        if constraint.name is not None
    }

    assert "tenant_id" in columns
    assert "parent_category_id" in columns
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["parent_category_id"].foreign_keys
    } == {"categories"}
    assert "name" in columns
    assert "slug" in columns
    assert columns["category_type"].default is not None
    assert columns["category_type"].default.arg == CategoryType.OTHER.value
    assert columns["is_system"].default is not None
    assert columns["is_system"].default.arg is False
    assert columns["is_active"].default is not None
    assert columns["is_active"].default.arg is True
    assert constraints["uq_categories_tenant_slug"] == {"tenant_id", "slug"}


def test_classification_proposal_columns_defaults_and_links() -> None:
    columns = ClassificationProposal.__table__.c

    assert "tenant_id" in columns
    assert "proposed_category_id" in columns
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["proposed_category_id"].foreign_keys
    } == {"categories"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["invoice_id"].foreign_keys
    } == {"invoices"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["invoice_line_item_id"].foreign_keys
    } == {"invoice_line_items"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["transaction_id"].foreign_keys
    } == {"transactions"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["supersedes_proposal_id"].foreign_keys
    } == {"classification_proposals"}
    assert "target_type" in columns
    assert columns["status"].default is not None
    assert columns["status"].default.arg == ClassificationProposalStatus.PROPOSED.value
    assert "version" in columns
    assert "confidence" in columns
    assert "rationale" in columns
    assert "evidence_refs" in columns
    assert "policy_flags" in columns
    assert "metadata" in columns


def test_reconciliation_columns_defaults_and_self_version_link() -> None:
    columns = Reconciliation.__table__.c

    assert "tenant_id" in columns
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["supersedes_reconciliation_id"].foreign_keys
    } == {"reconciliations"}
    assert columns["status"].default is not None
    assert columns["status"].default.arg == ReconciliationStatus.PROPOSED.value
    assert columns["match_type"].default is not None
    assert columns["match_type"].default.arg == ReconciliationMatchType.ONE_TO_ONE.value
    assert "version" in columns
    assert "currency" in columns
    assert "invoice_total_amount" in columns
    assert "transaction_total_amount" in columns
    assert "difference_amount" in columns
    assert "confidence" in columns
    assert "rationale" in columns
    assert "evidence_refs" in columns
    assert "metadata" in columns


def test_reconciliation_allocation_links_invoice_transaction_and_reconciliation() -> (
    None
):
    columns = ReconciliationAllocation.__table__.c

    assert "tenant_id" in columns
    assert columns["reconciliation_id"].index is True
    assert columns["reconciliation_id"].nullable is False
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["reconciliation_id"].foreign_keys
    } == {"reconciliations"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["invoice_id"].foreign_keys
    } == {"invoices"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["transaction_id"].foreign_keys
    } == {"transactions"}
    assert columns["status"].default is not None
    assert (
        columns["status"].default.arg == ReconciliationAllocationStatus.PROPOSED.value
    )
    assert "allocated_amount" in columns
    assert columns["allocated_amount"].nullable is False
    assert "currency" in columns
    assert "allocation_method" in columns
    assert "confidence" in columns
    assert "metadata" in columns


def test_accounting_enums_expose_stable_values() -> None:
    assert CategoryType.EXPENSE.value == "expense"
    assert ClassificationTargetType.TRANSACTION.value == "transaction"
    assert ClassificationProposalStatus.APPROVED.value == "approved"
    assert ReconciliationStatus.PENDING_REVIEW.value == "pending_review"
    assert ReconciliationMatchType.MANY_TO_ONE.value == "many_to_one"
    assert ReconciliationAllocationStatus.SUPERSEDED.value == "superseded"
