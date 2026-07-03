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
)
from app.evaluations.datasets import (
    dataset_manifest_path,
    ensure_safe_dataset_id,
)


def test_labelled_dataset_manifest_loads() -> None:
    manifest = load_dataset_manifest()

    assert manifest.schema_version == "evaluation.dataset-manifest.v1"
    assert manifest.dataset_id == DEFAULT_DATASET_ID
    assert manifest.version == "0.1.0"
    assert manifest.deidentification.synthetic_entities is True
    assert "real_tax_ids" in manifest.deidentification.removed_fields
    assert len(manifest.cases) == 3


def test_labelled_dataset_cases_describe_supported_evaluation_tasks() -> None:
    manifest = load_dataset_manifest()

    invoice_case = find_dataset_case(
        manifest=manifest,
        case_id="invoice_revenue_services_001",
    )
    assert invoice_case.document_type == EvaluationDocumentType.INVOICE
    assert EvaluationTaskKind.EXTRACTION in invoice_case.task_tags
    assert EvaluationTaskKind.RECONCILIATION in invoice_case.task_tags

    statement_case = find_dataset_case(
        manifest=manifest,
        case_id="statement_operating_july_2026",
    )
    assert statement_case.document_type == EvaluationDocumentType.BANK_STATEMENT
    assert EvaluationTaskKind.STATEMENT_PARSING in statement_case.task_tags
    assert EvaluationTaskKind.INSIGHT_GROUNDEDNESS in statement_case.task_tags


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


def test_labelled_dataset_loader_rejects_unsafe_dataset_ids() -> None:
    with pytest.raises(EvaluationDatasetPathError):
        ensure_safe_dataset_id("../sme_local_v1")

    with pytest.raises(EvaluationDatasetPathError):
        dataset_manifest_path("sme_local_v1.json")


def test_labelled_dataset_loader_reports_missing_case() -> None:
    manifest = load_dataset_manifest()

    with pytest.raises(EvaluationDatasetNotFoundError):
        find_dataset_case(manifest=manifest, case_id="missing_case")
