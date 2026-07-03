import pytest

from app.evaluations import (
    DEFAULT_DATASET_ID,
    EvaluationDatasetNotFoundError,
    EvaluationDatasetPathError,
    EvaluationDocumentType,
    EvaluationTaskKind,
    find_dataset_case,
    list_dataset_ids,
    load_dataset_fixture_text,
    load_dataset_manifest,
    load_expected_classification_label,
    load_expected_extraction_label,
    load_expected_label_payload,
    load_expected_reconciliation_label,
    load_expected_review_routing_label,
)
from app.evaluations.datasets import (
    dataset_manifest_path,
    ensure_safe_dataset_id,
)
from app.models.accounting import CategoryType, ClassificationTargetType
from app.models.invoice import InvoiceDirection
from app.models.operations import ReviewTaskPriority, ReviewTaskType
from app.workflows.contracts import ConfidenceLevel


def test_labelled_dataset_manifest_loads() -> None:
    manifest = load_dataset_manifest()

    assert manifest.schema_version == "evaluation.dataset-manifest.v1"
    assert manifest.dataset_id == DEFAULT_DATASET_ID
    assert manifest.version == "0.1.0"
    assert manifest.deidentification.synthetic_entities is True
    assert "real_tax_ids" in manifest.deidentification.removed_fields
    assert len(manifest.cases) == 3
    assert all(case.label_paths for case in manifest.cases)


def test_labelled_dataset_cases_describe_supported_evaluation_tasks() -> None:
    manifest = load_dataset_manifest()

    invoice_case = find_dataset_case(
        manifest=manifest,
        case_id="invoice_revenue_services_001",
    )
    assert invoice_case.document_type == EvaluationDocumentType.INVOICE
    assert EvaluationTaskKind.EXTRACTION in invoice_case.task_tags
    assert EvaluationTaskKind.RECONCILIATION in invoice_case.task_tags
    assert invoice_case.label_paths[EvaluationTaskKind.EXTRACTION].endswith(
        "invoice_revenue_services_001.expected.json"
    )

    statement_case = find_dataset_case(
        manifest=manifest,
        case_id="statement_operating_july_2026",
    )
    assert statement_case.document_type == EvaluationDocumentType.BANK_STATEMENT
    assert EvaluationTaskKind.STATEMENT_PARSING in statement_case.task_tags
    assert EvaluationTaskKind.INSIGHT_GROUNDEDNESS in statement_case.task_tags
    assert EvaluationTaskKind.REVIEW_ROUTING in statement_case.task_tags


def test_labelled_dataset_fixture_text_loads_for_invoice_and_statement() -> None:
    invoice_text = load_dataset_fixture_text(
        case_id="invoice_revenue_services_001",
    )
    statement_text = load_dataset_fixture_text(
        case_id="statement_operating_july_2026",
    )

    assert "Invoice Number: INV-EVAL-001" in invoice_text
    assert "Supplier: Demo Advisory Studio LLC" in invoice_text
    assert "No real customer, bank, or tax data." in invoice_text
    assert "posted_at,value_at,direction,description" in statement_text
    assert "INV-EVAL-001,1100.00,USD" in statement_text


def test_labelled_dataset_ids_are_listable() -> None:
    assert DEFAULT_DATASET_ID in list_dataset_ids()


def test_expected_extraction_label_loads() -> None:
    label = load_expected_extraction_label(case_id="invoice_expense_saas_002")

    assert label.schema_version == "evaluation.expected-extraction.v1"
    assert label.case_id == "invoice_expense_saas_002"
    assert label.invoice_number == "BILL-EVAL-002"
    assert label.direction == InvoiceDirection.PAYABLE
    assert label.supplier_name == "Cloud Tools Example Inc."
    assert label.currency == "USD"
    assert label.total_amount == 150
    assert len(label.line_items) == 2
    assert label.line_items[0].description == "Team workspace subscription"
    assert "line_items" in label.required_fields


def test_expected_classification_label_loads() -> None:
    label = load_expected_classification_label(
        case_id="statement_operating_july_2026",
    )

    assert label.schema_version == "evaluation.expected-classification.v1"
    assert len(label.records) == 4
    assert label.records[0].source_ref == "transaction:INV-EVAL-001"
    assert label.records[0].target_type == ClassificationTargetType.TRANSACTION
    assert label.records[0].category_type == CategoryType.REVENUE
    assert label.records[1].category_code == "software_subscription"
    assert label.records[2].category_code == "advertising_expense"
    assert label.records[2].confidence_floor == ConfidenceLevel.MEDIUM


def test_expected_reconciliation_label_loads() -> None:
    label = load_expected_reconciliation_label(
        case_id="statement_operating_july_2026",
    )

    assert label.schema_version == "evaluation.expected-reconciliation.v1"
    assert len(label.expected_matches) == 2
    assert label.expected_matches[0].invoice_number == "INV-EVAL-001"
    assert label.expected_matches[0].transaction_reference == "INV-EVAL-001"
    assert label.expected_matches[0].min_score == 90
    assert label.expected_matches[0].confidence_floor == ConfidenceLevel.HIGH
    assert label.expected_unmatched_transaction_refs == [
        "ADS-JUL-2026",
        "RENT-JUL-2026",
    ]


def test_expected_review_routing_label_loads() -> None:
    invoice_label = load_expected_review_routing_label(
        case_id="invoice_revenue_services_001",
    )
    statement_label = load_expected_review_routing_label(
        case_id="statement_operating_july_2026",
    )

    assert invoice_label.should_create_review_task is False
    assert invoice_label.expected_tasks == []
    assert statement_label.should_create_review_task is True
    assert len(statement_label.expected_tasks) == 2
    assert statement_label.expected_tasks[0].task_type == ReviewTaskType.RECONCILIATION
    assert statement_label.expected_tasks[0].priority == ReviewTaskPriority.NORMAL
    assert (
        statement_label.expected_tasks[0].reason_code == "missing_supporting_document"
    )


def test_raw_expected_label_payload_loader_returns_payload_dict() -> None:
    payload = load_expected_label_payload(
        case_id="invoice_revenue_services_001",
        dataset_id=DEFAULT_DATASET_ID,
        task_kind=EvaluationTaskKind.EXTRACTION,
    )

    assert payload["schema_version"] == "evaluation.expected-extraction.v1"
    assert payload["case_id"] == "invoice_revenue_services_001"


def test_labelled_dataset_loader_rejects_unsafe_dataset_ids() -> None:
    with pytest.raises(EvaluationDatasetPathError):
        ensure_safe_dataset_id("../sme_local_v1")

    with pytest.raises(EvaluationDatasetPathError):
        dataset_manifest_path("sme_local_v1.json")


def test_labelled_dataset_loader_reports_missing_case() -> None:
    manifest = load_dataset_manifest()

    with pytest.raises(EvaluationDatasetNotFoundError):
        find_dataset_case(manifest=manifest, case_id="missing_case")
