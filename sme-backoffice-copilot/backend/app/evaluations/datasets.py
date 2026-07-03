"""Labelled evaluation dataset manifest contracts and loaders."""

from __future__ import annotations

import json
from enum import StrEnum
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

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


def ensure_safe_dataset_id(dataset_id: str) -> None:
    """Reject dataset IDs that could escape the evaluation dataset root."""

    if not dataset_id or Path(dataset_id).name != dataset_id or Path(dataset_id).suffix:
        raise EvaluationDatasetPathError(
            f"Invalid evaluation dataset ID: {dataset_id!r}"
        )
