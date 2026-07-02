"""Mock OCR and LLM providers for deterministic local testing."""

from __future__ import annotations

import json
from copy import deepcopy

from app.providers.llm import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMProviderRunContext,
    LLMResponseFormat,
)
from app.providers.ocr import (
    OCRInput,
    OCRProviderRunContext,
    OCRResult,
    OCRTextBlock,
)

MOCK_PROVIDER_VERSION = "0.1.0"

DEFAULT_MOCK_OCR_TEXT = """Invoice #INV-MOCK-001
Supplier: Mock Supplier Ltd
Customer: SME Demo Company
Subtotal: 100.00
Tax: 10.00
Total: 110.00
Currency: USD"""


DEFAULT_STRUCTURED_OUTPUTS: dict[str, dict[str, object]] = {
    "invoice-metadata-group.v1": {
        "schema_version": "invoice-metadata-group.v1",
        "extraction_status": "extracted",
        "invoice_number": "INV-MOCK-001",
        "supplier_name": "Mock Supplier Ltd",
        "supplier_tax_id": "MOCK-SUPPLIER-TAX",
        "customer_name": "SME Demo Company",
        "customer_tax_id": "MOCK-CUSTOMER-TAX",
        "issue_date": "2026-07-01",
        "due_date": "2026-07-15",
        "currency": "USD",
        "evidence_refs": ["mock:page:1"],
        "confidence": "high",
    },
    "invoice-table-group.v1": {
        "schema_version": "invoice-table-group.v1",
        "extraction_status": "extracted",
        "line_items": [
            {
                "line_number": 1,
                "description": "Mock consulting service",
                "quantity": "1",
                "unit_price": "100.00",
                "tax_amount": "10.00",
                "line_total": "110.00",
                "evidence_refs": ["mock:page:1:table:row:1"],
                "confidence": "high",
            }
        ],
        "table_region_ref": "mock:page:1:table",
        "evidence_refs": ["mock:page:1:table"],
        "confidence": "high",
    },
    "invoice-totals-group.v1": {
        "schema_version": "invoice-totals-group.v1",
        "extraction_status": "extracted",
        "subtotal_amount": "100.00",
        "tax_amount": "10.00",
        "total_amount": "110.00",
        "currency": "USD",
        "evidence_refs": ["mock:page:1:totals"],
        "confidence": "high",
    },
    "classification-draft.v1": {
        "schema_version": "classification-draft.v1",
        "classification_status": "placeholder",
        "subject_type": "invoice",
        "subject_ref": "assembled_invoice_draft",
        "proposed_category_code": "professional_services",
        "proposed_direction": "income",
        "rationale": "Mock classification based on fixture supplier and line item.",
        "evidence_refs": ["mock:page:1"],
        "confidence": "high",
    },
}


class MockOCRProvider:
    """Deterministic OCR provider used for tests and local workflow replay."""

    def __init__(
        self,
        *,
        full_text: str = DEFAULT_MOCK_OCR_TEXT,
        language: str = "en",
        confidence: float = 0.99,
    ) -> None:
        self.full_text = full_text
        self.language = language
        self.confidence = confidence

    @property
    def name(self) -> str:
        """Return the stable mock OCR provider name."""

        return "mock_ocr"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Return deterministic OCR text and line-level text blocks."""

        full_text = self._resolve_full_text(input_data)
        text_blocks = [
            OCRTextBlock(
                text=line,
                page_number=1,
                confidence=self.confidence,
                metadata={"source": "mock_ocr", "line_index": index},
            )
            for index, line in enumerate(full_text.splitlines(), start=1)
            if line.strip()
        ]
        return OCRResult(
            provider_name=self.name,
            provider_version=MOCK_PROVIDER_VERSION,
            language=self.language,
            full_text=full_text,
            text_blocks=text_blocks,
            confidence=self.confidence,
            metadata={
                "artifact_uri": input_data.artifact_uri,
                "content_hash": input_data.content_hash,
                "tenant_id": str(context.tenant_id),
                "document_id": str(context.document_id),
                "workflow_run_id": str(context.workflow_run_id)
                if context.workflow_run_id is not None
                else None,
                "correlation_id": context.correlation_id,
            },
        )

    def _resolve_full_text(self, input_data: OCRInput) -> str:
        """Return per-call mock text when provided, otherwise the default text."""

        mock_full_text = input_data.metadata.get("mock_full_text")
        if isinstance(mock_full_text, str) and mock_full_text.strip():
            return mock_full_text
        return self.full_text


class MockLLMProvider:
    """Deterministic LLM provider used for tests and local workflow replay."""

    def __init__(
        self,
        *,
        model_name: str = "mock-llm",
        structured_outputs: dict[str, dict[str, object]] | None = None,
    ) -> None:
        self.model_name = model_name
        self.structured_outputs = structured_outputs or DEFAULT_STRUCTURED_OUTPUTS

    @property
    def name(self) -> str:
        """Return the stable mock LLM provider name."""

        return "mock_llm"

    async def generate(
        self,
        *,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> LLMGenerationResult:
        """Return deterministic text or structured JSON output."""

        if request.response_format == LLMResponseFormat.TEXT:
            output_text = self._text_response_for(request)
            structured_output: dict[str, object] | None = None
        else:
            structured_output = self._structured_response_for(request, context)
            output_text = json.dumps(
                structured_output,
                sort_keys=True,
                separators=(",", ":"),
            )

        return LLMGenerationResult(
            provider_name=self.name,
            model_name=self.model_name,
            output_text=output_text,
            structured_output=structured_output,
            input_tokens=self._estimate_tokens(
                " ".join(message.content for message in request.messages)
            ),
            output_tokens=self._estimate_tokens(output_text),
            latency_ms=0,
            metadata={
                "response_schema_name": request.response_schema_name,
                "response_format": request.response_format.value,
                "agent_name": context.agent_name,
                "tenant_id": str(context.tenant_id),
                "document_id": str(context.document_id)
                if context.document_id is not None
                else None,
                "workflow_run_id": str(context.workflow_run_id)
                if context.workflow_run_id is not None
                else None,
                "correlation_id": context.correlation_id,
            },
        )

    def _structured_response_for(
        self,
        request: LLMGenerationRequest,
        context: LLMProviderRunContext,
    ) -> dict[str, object]:
        """Return schema-specific mock structured output."""

        schema_name = request.response_schema_name
        if schema_name is not None and schema_name in self.structured_outputs:
            return deepcopy(self.structured_outputs[schema_name])
        return {
            "schema_version": schema_name or "mock-llm-output.v1",
            "mock": True,
            "agent_name": context.agent_name,
            "message_count": len(request.messages),
        }

    def _text_response_for(self, request: LLMGenerationRequest) -> str:
        """Return deterministic mock text for text-format requests."""

        schema_name = request.response_schema_name or "unstructured"
        return f"Mock LLM response for {schema_name}."

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        """Return a simple deterministic token estimate for tests."""

        return len([token for token in text.split() if token])
