"""Labelled evaluation dataset manifest contracts and loaders."""

from __future__ import annotations

import json
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from app.models.accounting import (
    CategoryType,
    ClassificationTargetType,
    ReconciliationMatchType,
)
from app.models.invoice import InvoiceDirection
from app.models.operations import ReviewTaskPriority, ReviewTaskType
from app.workflows.contracts import ConfidenceLevel

EVALUATION_DATASET_ROOT = Path(__file__).parent / "datasets"
DEFAULT_DATASET_ID = "sme_local_v1"


class EvaluationDatasetError(RuntimeError):
    """Base error for evaluation dataset loading failures."""


class EvaluationDatasetNotFoundError(EvaluationDatasetError):
    """Raised when a requested evaluation dataset does not exist."""


class EvaluationDatasetPathError(EvaluationDatasetError):
    """Raised when a dataset references an unsafe fixture path."""


class EvaluationDocumentType(StrEnum):
    """Document families supported by labelled evaluation datasets."""

    INVOICE = "invoice"
    BANK_STATEMENT = "bank_statement"


class EvaluationTaskKind(StrEnum):
    """Evaluation tasks that a dataset case may support."""

    EXTRACTION = "extraction"
    STATEMENT_PARSING = "statement_parsing"
    CLASSIFICATION = "classification"
    RECONCILIATION = "reconciliation"
    REVIEW_ROUTING = "review_routing"
    INSIGHT_GROUNDEDNESS = "insight_groundedness"


class EvaluationDeidentificationInfo(BaseModel):
    """How sensitive source data was removed before entering the dataset."""

    model_config = ConfigDict(extra="forbid")

    method: str = Field(min_length=1)
    removed_fields: list[str] = Field(default_factory=list)
    synthetic_entities: bool = True
    notes: str | None = None


class EvaluationDatasetCase(BaseModel):
    """One source document and its future expected-label references."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    document_type: EvaluationDocumentType
    fixture_path: str = Field(min_length=1)
    mime_type: str = Field(min_length=1)
    task_tags: list[EvaluationTaskKind] = Field(min_length=1)
    label_paths: dict[EvaluationTaskKind, str] = Field(default_factory=dict)
    notes: str | None = None


class EvaluationDatasetManifest(BaseModel):
    """Manifest describing a versioned, de-identified evaluation dataset."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evaluation.dataset-manifest.v1"
    dataset_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    deidentification: EvaluationDeidentificationInfo
    cases: list[EvaluationDatasetCase] = Field(min_length=1)


class ExpectedInvoiceLineItemLabel(BaseModel):
    """Expected structured invoice line item for extraction evaluation."""

    model_config = ConfigDict(extra="forbid")

    line_number: int = Field(ge=1)
    description: str = Field(min_length=1)
    quantity: Decimal
    unit_price: Decimal
    tax_amount: Decimal
    line_total: Decimal


class ExpectedExtractionLabel(BaseModel):
    """Expected invoice extraction output for one invoice document."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evaluation.expected-extraction.v1"
    case_id: str = Field(min_length=1)
    invoice_number: str = Field(min_length=1)
    direction: InvoiceDirection
    supplier_name: str = Field(min_length=1)
    supplier_tax_id: str | None = None
    customer_name: str = Field(min_length=1)
    customer_tax_id: str | None = None
    issue_date: str = Field(min_length=1)
    due_date: str | None = None
    currency: str = Field(min_length=3, max_length=3)
    subtotal_amount: Decimal
    tax_amount: Decimal
    total_amount: Decimal
    line_items: list[ExpectedInvoiceLineItemLabel] = Field(min_length=1)
    required_fields: list[str] = Field(default_factory=list)
    amount_tolerance: Decimal = Decimal("0.01")


class ExpectedClassificationRecordLabel(BaseModel):
    """Expected accounting classification for one target record."""

    model_config = ConfigDict(extra="forbid")

    source_ref: str = Field(min_length=1)
    target_type: ClassificationTargetType
    category_code: str = Field(min_length=1)
    category_type: CategoryType
    expected_direction: str = Field(min_length=1)
    confidence_floor: ConfidenceLevel = ConfidenceLevel.UNKNOWN
    rationale_keywords: list[str] = Field(default_factory=list)


class ExpectedClassificationLabel(BaseModel):
    """Expected classification labels for one dataset case."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evaluation.expected-classification.v1"
    case_id: str = Field(min_length=1)
    records: list[ExpectedClassificationRecordLabel] = Field(min_length=1)


class ExpectedReconciliationMatchLabel(BaseModel):
    """Expected invoice-to-transaction reconciliation match."""

    model_config = ConfigDict(extra="forbid")

    invoice_case_id: str = Field(min_length=1)
    invoice_number: str = Field(min_length=1)
    statement_case_id: str = Field(min_length=1)
    transaction_reference: str = Field(min_length=1)
    transaction_id: str = Field(min_length=1)
    match_type: ReconciliationMatchType = ReconciliationMatchType.ONE_TO_ONE
    amount: Decimal
    currency: str = Field(min_length=3, max_length=3)
    min_score: int = Field(default=70, ge=0, le=100)
    confidence_floor: ConfidenceLevel = ConfidenceLevel.UNKNOWN


class ExpectedReconciliationLabel(BaseModel):
    """Expected reconciliation labels for one dataset case."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evaluation.expected-reconciliation.v1"
    case_id: str = Field(min_length=1)
    expected_matches: list[ExpectedReconciliationMatchLabel] = Field(
        default_factory=list
    )
    expected_unmatched_transaction_refs: list[str] = Field(default_factory=list)


class ExpectedReviewTaskLabel(BaseModel):
    """Expected review task routed from one case."""

    model_config = ConfigDict(extra="forbid")

    task_type: ReviewTaskType
    target_ref: str = Field(min_length=1)
    reason_code: str = Field(min_length=1)
    priority: ReviewTaskPriority = ReviewTaskPriority.NORMAL


class ExpectedReviewRoutingLabel(BaseModel):
    """Expected human-review routing behavior for one case."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = "evaluation.expected-review-routing.v1"
    case_id: str = Field(min_length=1)
    should_create_review_task: bool
    expected_tasks: list[ExpectedReviewTaskLabel] = Field(default_factory=list)
    notes: str | None = None


def load_dataset_manifest(
    dataset_id: str = DEFAULT_DATASET_ID,
) -> EvaluationDatasetManifest:
    """Load and validate one evaluation dataset manifest."""

    manifest_path = dataset_manifest_path(dataset_id)
    if not manifest_path.exists():
        raise EvaluationDatasetNotFoundError(
            f"Evaluation dataset does not exist: {dataset_id}"
        )

    payload = cast(
        dict[str, object],
        json.loads(manifest_path.read_text(encoding="utf-8")),
    )
    manifest = EvaluationDatasetManifest.model_validate(payload)

    for case in manifest.cases:
        dataset_fixture_path(dataset_id=manifest.dataset_id, case=case)
        for task_kind, label_path in case.label_paths.items():
            if task_kind not in case.task_tags:
                raise EvaluationDatasetPathError(
                    f"Label kind {task_kind.value!r} is not declared in task_tags "
                    f"for case {case.case_id!r}"
                )
            dataset_label_path(dataset_id=manifest.dataset_id, label_path=label_path)

    return manifest


def list_dataset_ids() -> list[str]:
    """Return dataset IDs that have a manifest file."""

    if not EVALUATION_DATASET_ROOT.exists():
        return []

    return sorted(
        path.name
        for path in EVALUATION_DATASET_ROOT.iterdir()
        if path.is_dir() and (path / "manifest.json").exists()
    )


def load_dataset_fixture_text(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    case_id: str,
) -> str:
    """Load a text fixture for one case in a dataset."""

    manifest = load_dataset_manifest(dataset_id)
    case = find_dataset_case(manifest=manifest, case_id=case_id)
    return dataset_fixture_path(dataset_id=dataset_id, case=case).read_text(
        encoding="utf-8"
    )


def load_expected_extraction_label(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    case_id: str,
) -> ExpectedExtractionLabel:
    """Load and validate expected extraction labels for one case."""

    return ExpectedExtractionLabel.model_validate(
        load_expected_label_payload(
            dataset_id=dataset_id,
            case_id=case_id,
            task_kind=EvaluationTaskKind.EXTRACTION,
        )
    )


def load_expected_classification_label(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    case_id: str,
) -> ExpectedClassificationLabel:
    """Load and validate expected classification labels for one case."""

    return ExpectedClassificationLabel.model_validate(
        load_expected_label_payload(
            dataset_id=dataset_id,
            case_id=case_id,
            task_kind=EvaluationTaskKind.CLASSIFICATION,
        )
    )


def load_expected_reconciliation_label(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    case_id: str,
) -> ExpectedReconciliationLabel:
    """Load and validate expected reconciliation labels for one case."""

    return ExpectedReconciliationLabel.model_validate(
        load_expected_label_payload(
            dataset_id=dataset_id,
            case_id=case_id,
            task_kind=EvaluationTaskKind.RECONCILIATION,
        )
    )


def load_expected_review_routing_label(
    *,
    dataset_id: str = DEFAULT_DATASET_ID,
    case_id: str,
) -> ExpectedReviewRoutingLabel:
    """Load and validate expected review-routing labels for one case."""

    return ExpectedReviewRoutingLabel.model_validate(
        load_expected_label_payload(
            dataset_id=dataset_id,
            case_id=case_id,
            task_kind=EvaluationTaskKind.REVIEW_ROUTING,
        )
    )


def load_expected_label_payload(
    *,
    dataset_id: str,
    case_id: str,
    task_kind: EvaluationTaskKind,
) -> dict[str, object]:
    """Load a raw expected-label payload from one manifest case."""

    manifest = load_dataset_manifest(dataset_id)
    case = find_dataset_case(manifest=manifest, case_id=case_id)
    label_path = case.label_paths.get(task_kind)
    if label_path is None:
        raise EvaluationDatasetNotFoundError(
            f"Expected label does not exist: {dataset_id}/{case_id}/{task_kind.value}"
        )

    path = dataset_label_path(dataset_id=dataset_id, label_path=label_path)
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def find_dataset_case(
    *,
    manifest: EvaluationDatasetManifest,
    case_id: str,
) -> EvaluationDatasetCase:
    """Return one case from a manifest by case ID."""

    for case in manifest.cases:
        if case.case_id == case_id:
            return case

    raise EvaluationDatasetNotFoundError(
        f"Evaluation dataset case does not exist: {manifest.dataset_id}/{case_id}"
    )


def dataset_manifest_path(dataset_id: str) -> Path:
    """Return the manifest path for one dataset ID."""

    ensure_safe_dataset_id(dataset_id)
    return EVALUATION_DATASET_ROOT / dataset_id / "manifest.json"


def dataset_fixture_path(
    *,
    dataset_id: str,
    case: EvaluationDatasetCase,
) -> Path:
    """Return a safe absolute fixture path for a dataset case."""

    ensure_safe_dataset_id(dataset_id)
    dataset_root = (EVALUATION_DATASET_ROOT / dataset_id).resolve()
    fixture_path = (dataset_root / case.fixture_path).resolve()

    if not str(fixture_path).startswith(f"{dataset_root}{Path('/')}"):
        raise EvaluationDatasetPathError(
            f"Evaluation fixture path escapes dataset root: {case.fixture_path}"
        )

    if not fixture_path.exists():
        raise EvaluationDatasetNotFoundError(
            f"Evaluation fixture does not exist: {case.fixture_path}"
        )

    return fixture_path


def dataset_label_path(
    *,
    dataset_id: str,
    label_path: str,
) -> Path:
    """Return a safe absolute expected-label path for a dataset case."""

    ensure_safe_dataset_id(dataset_id)
    dataset_root = (EVALUATION_DATASET_ROOT / dataset_id).resolve()
    resolved_label_path = (dataset_root / label_path).resolve()

    if not str(resolved_label_path).startswith(f"{dataset_root}{Path('/')}"):
        raise EvaluationDatasetPathError(
            f"Evaluation label path escapes dataset root: {label_path}"
        )

    if not resolved_label_path.exists():
        raise EvaluationDatasetNotFoundError(
            f"Evaluation label does not exist: {label_path}"
        )

    return resolved_label_path


def ensure_safe_dataset_id(dataset_id: str) -> None:
    """Reject dataset IDs that could escape the evaluation dataset root."""

    if not dataset_id or Path(dataset_id).name != dataset_id or Path(dataset_id).suffix:
        raise EvaluationDatasetPathError(
            f"Invalid evaluation dataset ID: {dataset_id!r}"
        )
