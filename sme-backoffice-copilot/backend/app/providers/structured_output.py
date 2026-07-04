"""Structured output validation for provider JSON responses."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.insights import GroundedInsight, GroundedInsightPackage
from app.workflows.downstream_agents import (
    BusinessInsightDraft,
    ClassificationDraft,
    ReconciliationDraft,
    ReviewCoordinationDraft,
)
from app.workflows.invoice_extraction import (
    AssembledInvoiceDraft,
    InvoiceExtractionGroups,
    InvoiceMetadataGroup,
    InvoiceTableGroup,
    InvoiceTotalsGroup,
)

StructuredOutputModel = type[BaseModel]

DEFAULT_STRUCTURED_OUTPUT_SCHEMAS: dict[str, StructuredOutputModel] = {
    "invoice-metadata-group.v1": InvoiceMetadataGroup,
    "invoice-table-group.v1": InvoiceTableGroup,
    "invoice-totals-group.v1": InvoiceTotalsGroup,
    "invoice-extraction-groups.v1": InvoiceExtractionGroups,
    "assembled-invoice-draft.v1": AssembledInvoiceDraft,
    "classification-draft.v1": ClassificationDraft,
    "reconciliation-draft.v1": ReconciliationDraft,
    "review-coordination-draft.v1": ReviewCoordinationDraft,
    "business-insight-draft.v1": BusinessInsightDraft,
    "grounded-insight.v1": GroundedInsight,
    "grounded-insight-package.v1": GroundedInsightPackage,
}


class StructuredOutputValidationResult(BaseModel):
    """Result of validating provider JSON against a registered schema."""

    model_config = ConfigDict(extra="forbid")

    schema_name: str = Field(min_length=1)
    passed: bool
    schema_registered: bool
    normalized_output: dict[str, object] | None = None
    errors: list[str] = Field(default_factory=list)


def is_registered_output_schema(
    schema_name: str,
    *,
    schema_registry: Mapping[str, StructuredOutputModel] = (
        DEFAULT_STRUCTURED_OUTPUT_SCHEMAS
    ),
) -> bool:
    """Return whether a structured output schema is registered."""

    return schema_name in schema_registry


def validate_structured_output(
    *,
    schema_name: str,
    payload: Mapping[str, object],
    schema_registry: Mapping[str, StructuredOutputModel] = (
        DEFAULT_STRUCTURED_OUTPUT_SCHEMAS
    ),
) -> StructuredOutputValidationResult:
    """Validate a provider JSON payload against a registered Pydantic model."""

    schema_model = schema_registry.get(schema_name)
    if schema_model is None:
        return StructuredOutputValidationResult(
            schema_name=schema_name,
            passed=False,
            schema_registered=False,
            errors=[f"Structured output schema is not registered: {schema_name}"],
        )

    try:
        validated = schema_model.model_validate(dict(payload))
    except ValidationError as exc:
        return StructuredOutputValidationResult(
            schema_name=schema_name,
            passed=False,
            schema_registered=True,
            errors=[
                format_validation_error(error)
                for error in exc.errors(include_url=False)
            ],
        )

    return StructuredOutputValidationResult(
        schema_name=schema_name,
        passed=True,
        schema_registered=True,
        normalized_output=cast(
            dict[str, object],
            validated.model_dump(mode="json"),
        ),
    )


def parse_and_validate_structured_output(
    *,
    schema_name: str,
    output_text: str,
    schema_registry: Mapping[str, StructuredOutputModel] = (
        DEFAULT_STRUCTURED_OUTPUT_SCHEMAS
    ),
) -> StructuredOutputValidationResult:
    """Parse provider JSON text and validate it against a registered schema."""

    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        return StructuredOutputValidationResult(
            schema_name=schema_name,
            passed=False,
            schema_registered=is_registered_output_schema(
                schema_name,
                schema_registry=schema_registry,
            ),
            errors=[f"Invalid JSON: {exc.msg}"],
        )

    if not isinstance(payload, dict):
        return StructuredOutputValidationResult(
            schema_name=schema_name,
            passed=False,
            schema_registered=is_registered_output_schema(
                schema_name,
                schema_registry=schema_registry,
            ),
            errors=["Structured output JSON must be an object."],
        )

    return validate_structured_output(
        schema_name=schema_name,
        payload=cast(dict[str, object], payload),
        schema_registry=schema_registry,
    )


def format_validation_error(error: Any) -> str:
    """Format a Pydantic validation error compactly for metadata/reporting."""

    location = error.get("loc")
    message = error.get("msg")
    if isinstance(location, tuple):
        path = ".".join(str(part) for part in location)
    else:
        path = str(location or "payload")
    return f"{path}: {message}"
