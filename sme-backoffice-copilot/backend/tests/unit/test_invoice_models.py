from app.models import (
    Invoice,
    InvoiceDirection,
    InvoiceFieldEvidence,
    InvoiceLineItem,
    InvoiceStatus,
)
from app.models.base import Base


def test_invoice_tables_are_registered_in_metadata() -> None:
    assert "invoices" in Base.metadata.tables
    assert "invoice_line_items" in Base.metadata.tables
    assert "invoice_field_evidence" in Base.metadata.tables


def test_invoice_model_columns_and_defaults() -> None:
    columns = Invoice.__table__.c

    assert "tenant_id" in columns
    assert "document_id" in columns
    assert "source_processing_run_id" in columns
    assert "supersedes_invoice_id" in columns
    assert "version" in columns
    assert columns["status"].default is not None
    assert columns["status"].default.arg == InvoiceStatus.EXTRACTED.value
    assert columns["direction"].default is not None
    assert columns["direction"].default.arg == InvoiceDirection.UNKNOWN.value
    assert "invoice_number" in columns
    assert "supplier_name" in columns
    assert "customer_name" in columns
    assert "issue_date" in columns
    assert "due_date" in columns
    assert "subtotal_amount" in columns
    assert "tax_amount" in columns
    assert "total_amount" in columns
    assert "confidence" in columns


def test_invoice_links_to_document_and_processing_run() -> None:
    columns = Invoice.__table__.c

    assert columns["document_id"].index is True
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["document_id"].foreign_keys
    } == {"documents"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["source_processing_run_id"].foreign_keys
    } == {"processing_runs"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["supersedes_invoice_id"].foreign_keys
    } == {"invoices"}


def test_invoice_line_item_links_to_invoice_and_has_line_number_constraint() -> None:
    columns = InvoiceLineItem.__table__.c
    constraints = {
        constraint.name: {column.name for column in constraint.columns}
        for constraint in InvoiceLineItem.__table__.constraints
        if constraint.name is not None
    }

    assert "tenant_id" in columns
    assert columns["invoice_id"].index is True
    assert columns["invoice_id"].nullable is False
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["invoice_id"].foreign_keys
    } == {"invoices"}
    assert "line_number" in columns
    assert "description" in columns
    assert "quantity" in columns
    assert "unit_price_amount" in columns
    assert "total_amount" in columns
    assert constraints["uq_invoice_line_items_invoice_line_number"] == {
        "invoice_id",
        "line_number",
    }


def test_invoice_field_evidence_links_to_source_records() -> None:
    columns = InvoiceFieldEvidence.__table__.c

    assert "tenant_id" in columns
    assert columns["invoice_id"].index is True
    assert columns["invoice_id"].nullable is False
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["invoice_id"].foreign_keys
    } == {"invoices"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["line_item_id"].foreign_keys
    } == {"invoice_line_items"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["document_id"].foreign_keys
    } == {"documents"}
    assert {
        foreign_key.column.table.name
        for foreign_key in columns["artifact_id"].foreign_keys
    } == {"document_artifacts"}
    assert "field_name" in columns
    assert "field_path" in columns
    assert "extracted_value" in columns
    assert "normalized_value" in columns
    assert "bounding_box" in columns
    assert "text_span" in columns
    assert "metadata" in columns


def test_invoice_enums_expose_stable_values() -> None:
    assert InvoiceDirection.PAYABLE.value == "payable"
    assert InvoiceDirection.RECEIVABLE.value == "receivable"
    assert InvoiceStatus.PENDING_REVIEW.value == "pending_review"
