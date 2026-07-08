"""Unit tests for the Azure DI prebuilt-invoice structured field parser.

Covers:
- Metadata group: InvoiceId, VendorName, CustomerName, dates, currency
- Table group: Items array mapping to InvoiceLineItemCandidate shape
- Totals group: SubTotal, TotalTax, InvoiceTotal amounts
- Currency code resolution (explicit code, symbol fallback, cross-field)
- Backward compatibility: prebuilt-layout returns no prebuilt_invoice_extraction
- Edge cases: empty/missing fields, malformed response, no documents
"""

from __future__ import annotations

import pytest
from uuid import uuid4

from app.providers.azure_di import AzureDIOCRProvider


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_provider(model_id: str = "prebuilt-invoice") -> AzureDIOCRProvider:
    """Return a provider instance with dummy credentials (no network calls)."""
    return AzureDIOCRProvider(
        endpoint="https://example.cognitiveservices.azure.com",
        key="fake-key-000",
        model_id=model_id,
    )


def _currency_field(amount: float, code: str = "USD") -> dict:
    return {
        "type": "currency",
        "valueCurrency": {"amount": amount, "currencyCode": code},
        "content": f"${amount}",
    }


def _string_field(value: str) -> dict:
    return {"type": "string", "valueString": value, "content": value}


def _date_field(value: str) -> dict:
    return {"type": "date", "valueDate": value, "content": value}


def _item_object(
    description: str | None = "Widget",
    quantity: float | None = 2.0,
    unit_price: float | None = 50.0,
    amount: float | None = 100.0,
) -> dict:
    obj: dict = {}
    if description is not None:
        obj["Description"] = _string_field(description)
    if quantity is not None:
        obj["Quantity"] = {"type": "number", "valueNumber": quantity}
    if unit_price is not None:
        obj["UnitPrice"] = _currency_field(unit_price)
    if amount is not None:
        obj["Amount"] = _currency_field(amount)
    return {"type": "object", "valueObject": obj}


def _minimal_response(
    fields: dict,
    include_paragraphs: bool = False,
) -> dict:
    """Return the minimal analyzeResult payload shape Azure DI returns."""
    return {
        "analyzeResult": {
            "documents": [{"docType": "invoice", "fields": fields}],
            "paragraphs": [{"content": "Invoice text"}] if include_paragraphs else [],
            "pages": [],
        }
    }


# ─── _parse_prebuilt_invoice_fields directly ──────────────────────────────────


class TestParsePrebuiltInvoiceFields:
    """Tests for the private _parse_prebuilt_invoice_fields method."""

    def test_empty_documents_returns_empty_dict(self) -> None:
        provider = _make_provider()
        result = provider._parse_prebuilt_invoice_fields(
            result_payload={"analyzeResult": {"documents": [], "pages": []}}
        )
        assert result == {}

    def test_missing_documents_key_returns_empty_dict(self) -> None:
        provider = _make_provider()
        result = provider._parse_prebuilt_invoice_fields(result_payload={})
        assert result == {}

    def test_missing_fields_key_returns_empty_dict(self) -> None:
        provider = _make_provider()
        result = provider._parse_prebuilt_invoice_fields(
            result_payload={
                "analyzeResult": {"documents": [{"docType": "invoice"}], "pages": []}
            }
        )
        assert result == {}

    def test_metadata_group_extracted_correctly(self) -> None:
        provider = _make_provider()
        fields = {
            "InvoiceId": _string_field("INV-2024-001"),
            "VendorName": _string_field("East Repair Inc."),
            "CustomerName": _string_field("John Smith"),
            "InvoiceDate": _date_field("2024-01-15"),
            "DueDate": _date_field("2024-02-15"),
            "InvoiceTotal": _currency_field(154.06, "USD"),
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        meta = result["metadata_group"]
        assert meta["schema_version"] == "invoice-metadata-group.v1"
        assert meta["extraction_status"] == "extracted"
        assert meta["invoice_number"] == "INV-2024-001"
        assert meta["supplier_name"] == "East Repair Inc."
        assert meta["customer_name"] == "John Smith"
        assert meta["issue_date"] == "2024-01-15"
        assert meta["due_date"] == "2024-02-15"
        assert meta["currency"] == "USD"
        assert meta["confidence"] == "high"
        assert "azure_di:prebuilt-invoice" in meta["evidence_refs"]

    def test_customer_name_falls_back_to_address_recipient(self) -> None:
        provider = _make_provider()
        fields = {
            "VendorName": _string_field("Vendor Co"),
            # No CustomerName, use CustomerAddressRecipient
            "CustomerAddressRecipient": _string_field("Acme Corp"),
            "InvoiceTotal": _currency_field(100.0, "EUR"),
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["metadata_group"]["customer_name"] == "Acme Corp"

    def test_currency_derived_from_invoice_total(self) -> None:
        provider = _make_provider()
        fields = {"InvoiceTotal": _currency_field(200.0, "GBP")}
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["metadata_group"]["currency"] == "GBP"
        assert result["totals_group"]["currency"] == "GBP"

    def test_currency_symbol_fallback_maps_to_iso_code(self) -> None:
        provider = _make_provider()
        # Simulate Azure DI returning a symbol instead of a code
        fields = {
            "InvoiceTotal": {
                "type": "currency",
                "valueCurrency": {"amount": 500.0, "currencySymbol": "$"},
                "content": "$500.00",
            }
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["metadata_group"]["currency"] == "USD"

    def test_table_group_with_line_items(self) -> None:
        provider = _make_provider()
        fields = {
            "Items": {
                "type": "array",
                "valueArray": [
                    _item_object("Widget A", 2.0, 50.0, 100.0),
                    _item_object("Service B", 1.0, 75.0, 75.0),
                ],
            }
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        table = result["table_group"]
        assert table["schema_version"] == "invoice-table-group.v1"
        assert table["extraction_status"] == "extracted"
        assert len(table["line_items"]) == 2
        item_0 = table["line_items"][0]
        assert item_0["line_number"] == 1
        assert item_0["description"] == "Widget A"
        assert item_0["quantity"] == "2.0"
        assert item_0["unit_price"] == "50.00"
        assert item_0["line_total"] == "100.00"
        assert item_0["confidence"] == "high"
        assert "azure_di:prebuilt-invoice:item:1" in item_0["evidence_refs"]

    def test_table_group_empty_items_returns_placeholder(self) -> None:
        provider = _make_provider()
        fields = {"Items": {"type": "array", "valueArray": []}}
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["table_group"]["extraction_status"] == "placeholder"
        assert result["table_group"]["line_items"] == []
        assert result["table_group"]["confidence"] == "unknown"

    def test_table_group_absent_items_field(self) -> None:
        provider = _make_provider()
        fields = {"InvoiceId": _string_field("001")}
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["table_group"]["line_items"] == []

    def test_totals_group_all_fields(self) -> None:
        provider = _make_provider()
        fields = {
            "SubTotal": _currency_field(250.0, "USD"),
            "TotalTax": _currency_field(12.50, "USD"),
            "InvoiceTotal": _currency_field(262.50, "USD"),
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        totals = result["totals_group"]
        assert totals["schema_version"] == "invoice-totals-group.v1"
        assert totals["extraction_status"] == "extracted"
        assert totals["subtotal_amount"] == "250.00"
        assert totals["tax_amount"] == "12.50"
        assert totals["total_amount"] == "262.50"
        assert totals["confidence"] == "high"

    def test_totals_group_falls_back_to_amount_due(self) -> None:
        provider = _make_provider()
        # No InvoiceTotal; use AmountDue
        fields = {"AmountDue": _currency_field(99.00, "USD")}
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["totals_group"]["total_amount"] == "99.00"

    def test_totals_group_placeholder_when_no_amounts(self) -> None:
        provider = _make_provider()
        fields = {"InvoiceId": _string_field("001")}
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["totals_group"]["extraction_status"] == "placeholder"
        assert result["totals_group"]["total_amount"] is None

    def test_currency_amount_content_fallback(self) -> None:
        """When valueCurrency is absent, parse amount from content string."""
        provider = _make_provider()
        fields = {
            "InvoiceTotal": {
                "type": "currency",
                "content": "$154.06",
            }
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert result["totals_group"]["total_amount"] == "154.06"

    def test_result_keys_always_present(self) -> None:
        """Parser always returns all three group keys even with empty fields."""
        provider = _make_provider()
        fields = {}
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        assert "metadata_group" in result
        assert "table_group" in result
        assert "totals_group" in result


# ─── Backward compatibility: prebuilt-layout ──────────────────────────────────


class TestPrebuiltLayoutBackwardCompatibility:
    """Ensure prebuilt-layout mode never adds prebuilt_invoice_extraction."""

    def test_layout_provider_does_not_call_invoice_parser(self) -> None:
        provider = _make_provider(model_id="prebuilt-layout")
        # The private method should still work when called directly,
        # but _parse_result() should NOT call it for layout model.
        # We verify by checking the model_id guard directly.
        assert provider.model_id == "prebuilt-layout"
        assert provider.model_id != "prebuilt-invoice"

    def test_invoice_parser_not_invoked_for_layout_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """_parse_prebuilt_invoice_fields must NOT be called for layout model."""
        provider = _make_provider(model_id="prebuilt-layout")
        called = []

        original = provider._parse_prebuilt_invoice_fields

        def tracking_parse(**kwargs):  # type: ignore[no-untyped-def]
            called.append(True)
            return original(**kwargs)

        monkeypatch.setattr(provider, "_parse_prebuilt_invoice_fields", tracking_parse)

        # Simulate calling _parse_result with a minimal layout response
        from unittest.mock import MagicMock
        from app.providers.ocr import OCRInput, OCRProviderRunContext
        from uuid import uuid4

        dummy_input = OCRInput(
            artifact_uri="local://test",
            media_type="image/png",
            content_hash="abc123",
            local_path=None,
        )
        dummy_context = OCRProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
        )
        provider._parse_result(
            analyze_result={
                "analyzeResult": {
                    "paragraphs": [],
                    "pages": [],
                }
            },
            input_data=dummy_input,
            context=dummy_context,
        )
        assert called == [], "prebuilt parser must not be called for prebuilt-layout"

    def test_invoice_model_includes_prebuilt_extraction_in_metadata(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """prebuilt-invoice model stores extraction in OCRResult.metadata."""
        provider = _make_provider(model_id="prebuilt-invoice")
        from app.providers.ocr import OCRInput, OCRProviderRunContext
        from uuid import uuid4

        dummy_input = OCRInput(
            artifact_uri="local://test",
            media_type="image/png",
            content_hash="abc123",
        )
        dummy_context = OCRProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
        )
        analyze_result = {
            "analyzeResult": {
                "documents": [
                    {
                        "docType": "invoice",
                        "fields": {
                            "InvoiceId": _string_field("001"),
                            "VendorName": _string_field("Vendor"),
                            "InvoiceTotal": _currency_field(100.0, "USD"),
                        },
                    }
                ],
                "paragraphs": [{"content": "Invoice 001"}],
                "pages": [],
            }
        }
        ocr_result = provider._parse_result(
            analyze_result=analyze_result,
            input_data=dummy_input,
            context=dummy_context,
        )
        assert "prebuilt_invoice_extraction" in ocr_result.metadata
        extraction = ocr_result.metadata["prebuilt_invoice_extraction"]
        assert isinstance(extraction, dict)
        assert "metadata_group" in extraction
        assert "table_group" in extraction
        assert "totals_group" in extraction

    def test_layout_model_metadata_has_no_prebuilt_extraction(self) -> None:
        """prebuilt-layout model must never add prebuilt_invoice_extraction."""
        provider = _make_provider(model_id="prebuilt-layout")
        from app.providers.ocr import OCRInput, OCRProviderRunContext
        from uuid import uuid4

        dummy_input = OCRInput(
            artifact_uri="local://test",
            media_type="image/png",
            content_hash="abc123",
        )
        dummy_context = OCRProviderRunContext(
            tenant_id=uuid4(),
            document_id=uuid4(),
        )
        analyze_result = {
            "analyzeResult": {
                "paragraphs": [{"content": "Invoice 001"}],
                "pages": [],
            }
        }
        ocr_result = provider._parse_result(
            analyze_result=analyze_result,
            input_data=dummy_input,
            context=dummy_context,
        )
        assert "prebuilt_invoice_extraction" not in ocr_result.metadata


# ─── Financial plausibility check ─────────────────────────────────────────────


class TestFinancialPlausibilityCheck:
    """Tests for total_amount < subtotal_amount downgrade logic.

    Replicates the real-world scenario where a blue stamp on a receipt obscures
    the total so Azure DI returns '0.419' instead of '419' for InvoiceTotal.
    """

    def test_total_less_than_subtotal_sets_low_confidence(self) -> None:
        """When InvoiceTotal < SubTotal, totals_group confidence must be 'low'."""
        provider = _make_provider()
        fields = {
            "InvoiceTotal": _currency_field(0.419, "INR"),  # corrupted by stamp
            "SubTotal": _currency_field(355.0, "INR"),
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        totals = result["totals_group"]
        assert totals["confidence"] == "low"
        assert totals["extraction_status"] == "low_confidence"
        assert totals["total_amount"] == "0.42"   # value stored as-is; LLM corrects
        assert totals["subtotal_amount"] == "355.00"

    def test_total_equal_to_subtotal_no_downgrade(self) -> None:
        """When InvoiceTotal == SubTotal (no tax), confidence stays 'high'."""
        provider = _make_provider()
        fields = {
            "InvoiceTotal": _currency_field(355.0, "INR"),
            "SubTotal": _currency_field(355.0, "INR"),
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        totals = result["totals_group"]
        assert totals["confidence"] == "high"
        assert totals["extraction_status"] == "extracted"

    def test_normal_invoice_total_greater_than_subtotal_stays_high(self) -> None:
        """When InvoiceTotal > SubTotal (includes tax), confidence stays 'high'."""
        provider = _make_provider()
        fields = {
            "InvoiceTotal": _currency_field(418.90, "INR"),
            "SubTotal": _currency_field(355.0, "INR"),
            "TotalTax": _currency_field(63.90, "INR"),
        }
        result = provider._parse_prebuilt_invoice_fields(
            result_payload=_minimal_response(fields)
        )
        totals = result["totals_group"]
        assert totals["confidence"] == "high"
        assert totals["extraction_status"] == "extracted"

    def test_is_scratchpad_group_populated_rejects_low_confidence(self) -> None:
        """is_scratchpad_group_populated returns False for low-confidence groups."""
        from app.workflows.invoice_extraction import is_scratchpad_group_populated
        from app.workflows.langgraph_adapter import WorkflowState

        state = WorkflowState(
            tenant_id=uuid4(),
            document_id=uuid4(),
            document_type="invoice",
        )
        state.scratchpad["invoice_totals_group"] = {
            "confidence": "low",
            "total_amount": "0.42",
            "subtotal_amount": "355.00",
            "extraction_status": "low_confidence",
        }
        result = is_scratchpad_group_populated(
            state=state,
            scratchpad_key="invoice_totals_group",
            handoff=None,
        )
        assert result is False, "Low-confidence group must NOT be treated as populated"

    def test_is_scratchpad_group_populated_accepts_high_confidence(self) -> None:
        """is_scratchpad_group_populated returns True for high-confidence groups."""
        from app.workflows.invoice_extraction import is_scratchpad_group_populated
        from app.workflows.langgraph_adapter import WorkflowState

        state = WorkflowState(
            tenant_id=uuid4(),
            document_id=uuid4(),
            document_type="invoice",
        )
        state.scratchpad["invoice_totals_group"] = {
            "confidence": "high",
            "total_amount": "418.90",
            "subtotal_amount": "355.00",
            "extraction_status": "extracted",
        }
        result = is_scratchpad_group_populated(
            state=state,
            scratchpad_key="invoice_totals_group",
            handoff=None,
        )
        assert result is True, "High-confidence group must be treated as populated"

