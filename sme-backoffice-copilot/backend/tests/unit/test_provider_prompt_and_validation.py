import pytest

from app.providers import (
    DEFAULT_MOCK_OCR_TEXT,
    DEFAULT_PROMPT_REGISTRY,
    LLMMessageRole,
    ProviderPromptError,
    is_registered_output_schema,
    parse_and_validate_structured_output,
    validate_structured_output,
)
from app.providers.mock import DEFAULT_STRUCTURED_OUTPUTS


def test_default_prompt_registry_renders_invoice_metadata_prompt() -> None:
    rendered = DEFAULT_PROMPT_REGISTRY.render(
        prompt_id="invoice.metadata_extraction",
        variables={"ocr_text": DEFAULT_MOCK_OCR_TEXT},
    )

    assert rendered.prompt_id == "invoice.metadata_extraction"
    assert rendered.prompt_version == "0.1.0"
    assert rendered.response_schema_name == "invoice-metadata-group.v1"
    assert rendered.messages[0].role == LLMMessageRole.SYSTEM
    assert rendered.messages[1].role == LLMMessageRole.USER
    assert DEFAULT_MOCK_OCR_TEXT in rendered.messages[1].content


def test_prompt_registry_rejects_missing_required_variable() -> None:
    with pytest.raises(ProviderPromptError):
        DEFAULT_PROMPT_REGISTRY.render(
            prompt_id="invoice.metadata_extraction",
            variables={},
        )


def test_structured_output_validation_accepts_registered_schema() -> None:
    result = validate_structured_output(
        schema_name="invoice-metadata-group.v1",
        payload=DEFAULT_STRUCTURED_OUTPUTS["invoice-metadata-group.v1"],
    )

    assert result.passed is True
    assert result.schema_registered is True
    assert result.normalized_output is not None
    assert result.normalized_output["invoice_number"] == "INV-MOCK-001"


def test_structured_output_validation_rejects_extra_fields() -> None:
    payload = {
        **DEFAULT_STRUCTURED_OUTPUTS["invoice-metadata-group.v1"],
        "unexpected": "not allowed",
    }

    result = validate_structured_output(
        schema_name="invoice-metadata-group.v1",
        payload=payload,
    )

    assert result.passed is False
    assert result.schema_registered is True
    assert any("unexpected" in error for error in result.errors)


def test_structured_output_validation_reports_unknown_schema() -> None:
    result = validate_structured_output(
        schema_name="unknown-schema.v1",
        payload={"schema_version": "unknown-schema.v1"},
    )

    assert result.passed is False
    assert result.schema_registered is False
    assert result.errors == [
        "Structured output schema is not registered: unknown-schema.v1"
    ]


def test_parse_and_validate_structured_output_reports_invalid_json() -> None:
    result = parse_and_validate_structured_output(
        schema_name="invoice-metadata-group.v1",
        output_text="{invalid json",
    )

    assert result.passed is False
    assert result.schema_registered is True
    assert result.errors[0].startswith("Invalid JSON")


def test_registered_output_schema_lookup() -> None:
    assert is_registered_output_schema("classification-draft.v1") is True
    assert is_registered_output_schema("unknown-schema.v1") is False
