"""Azure Document Intelligence OCR provider using the REST API via httpx."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx

from app.providers.errors import (
    ProviderConfigurationError,
    ProviderExecutionError,
)
from app.providers.ocr import (
    OCRInput,
    OCRProviderRunContext,
    OCRResult,
    OCRTextBlock,
)

# Azure Document Intelligence API version
_API_VERSION = "2024-11-30"
# Polling interval in seconds while waiting for asynchronous analysis to complete
_POLL_INTERVAL_SECONDS = 0.5
# Maximum number of poll attempts (0.5s * 120 = 60 seconds max)
_MAX_POLL_ATTEMPTS = 120


class AzureDIOCRProvider:
    """OCR provider backed by Azure Document Intelligence (prebuilt-layout model).

    Sends the document binary to the Azure DI REST API, then polls until
    the analysis result is ready and maps the response to ``OCRResult``.

    No third-party Azure SDK is required; this uses ``httpx`` which is already
    present in the project.
    """

    def __init__(
        self,
        *,
        endpoint: str,
        key: str,
        model_id: str = "prebuilt-layout",
        timeout_seconds: float = 60.0,
    ) -> None:
        if not endpoint:
            raise ProviderConfigurationError(
                "AzureDIOCRProvider requires a non-empty 'endpoint'."
            )
        if not key:
            raise ProviderConfigurationError(
                "AzureDIOCRProvider requires a non-empty 'key'."
            )

        # Normalize endpoint: strip trailing slash
        self.endpoint = endpoint.rstrip("/")
        self.key = key
        self.model_id = model_id
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        """Return the stable Azure DI provider name."""

        return "azure_di"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Send the document to Azure DI and return normalized OCR blocks.

        The document binary is read from ``input_data.local_path``.
        Azure DI processes the document asynchronously; this method polls
        until the operation is complete.
        """

        if not input_data.local_path:
            raise ProviderConfigurationError(
                "AzureDIOCRProvider requires OCRInput.local_path to be set."
            )

        file_path = Path(input_data.local_path)
        if not file_path.exists():
            raise ProviderConfigurationError(
                f"Document file not found: {input_data.local_path}"
            )

        file_bytes = file_path.read_bytes()

        analyze_url = (
            f"{self.endpoint}/documentintelligence/documentModels"
            f"/{self.model_id}:analyze?api-version={_API_VERSION}"
        )

        headers = {
            "Ocp-Apim-Subscription-Key": self.key,
            "Content-Type": "application/octet-stream",
        }

        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            # Step 1: Submit document for analysis (returns 202 Accepted)
            response = await client.post(
                analyze_url,
                content=file_bytes,
                headers=headers,
            )

            if response.status_code not in (200, 202):
                raise ProviderExecutionError(
                    f"Azure DI analyze request failed: HTTP {response.status_code} — "
                    f"{response.text[:500]}"
                )

            operation_location = response.headers.get("Operation-Location")
            if not operation_location:
                raise ProviderExecutionError(
                    "Azure DI response did not include 'Operation-Location' header."
                )

            # Step 2: Poll for completion
            poll_headers = {"Ocp-Apim-Subscription-Key": self.key}
            analyze_result: dict[str, object] = {}

            for _ in range(_MAX_POLL_ATTEMPTS):
                await asyncio.sleep(_POLL_INTERVAL_SECONDS)

                poll_response = await client.get(
                    operation_location,
                    headers=poll_headers,
                )

                if poll_response.status_code != 200:
                    raise ProviderExecutionError(
                        f"Azure DI polling failed: HTTP {poll_response.status_code}"
                    )

                poll_data: dict[str, object] = poll_response.json()
                status = poll_data.get("status", "")

                if status == "succeeded":
                    analyze_result = poll_data
                    break
                elif status == "failed":
                    error_info = poll_data.get("error", {})
                    raise ProviderExecutionError(
                        f"Azure DI analysis failed: {error_info}"
                    )
                # status is "running" or "notStarted" — keep polling
            else:
                raise ProviderExecutionError(
                    f"Azure DI analysis timed out after "
                    f"{_MAX_POLL_ATTEMPTS * _POLL_INTERVAL_SECONDS:.0f} seconds."
                )

        return self._parse_result(
            analyze_result=analyze_result,
            input_data=input_data,
            context=context,
        )

    def _parse_result(
        self,
        *,
        analyze_result: dict[str, object],
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Parse the Azure DI analyze result into a normalized OCRResult."""

        result_payload = analyze_result.get("analyzeResult", {})
        assert isinstance(result_payload, dict)

        # Extract paragraphs as text blocks — highest-quality semantic units
        paragraphs = result_payload.get("paragraphs") or []
        assert isinstance(paragraphs, list)

        pages = result_payload.get("pages") or []
        assert isinstance(pages, list)

        text_blocks: list[OCRTextBlock] = []
        full_text_lines: list[str] = []

        for para in paragraphs:
            assert isinstance(para, dict)
            content = para.get("content", "")
            if not content or not isinstance(content, str):
                continue

            full_text_lines.append(content)

            # Determine page number from bounding region
            bounding_regions = para.get("boundingRegions") or []
            page_number = 1
            bounding_box: list[float] | None = None

            if bounding_regions and isinstance(bounding_regions, list):
                region = bounding_regions[0]
                assert isinstance(region, dict)
                page_number = int(region.get("pageNumber", 1))
                polygon = region.get("polygon")
                if polygon and isinstance(polygon, list):
                    bounding_box = [float(v) for v in polygon]

            text_blocks.append(
                OCRTextBlock(
                    text=content,
                    page_number=page_number,
                    bounding_box=bounding_box,
                    confidence=None,
                    metadata={"source": "azure_di_paragraph"},
                )
            )

        # Fallback: if no paragraphs, extract raw lines from the pages array
        if not text_blocks:
            for page in pages:
                assert isinstance(page, dict)
                page_number = int(page.get("pageNumber", 1))
                for line in page.get("lines") or []:
                    assert isinstance(line, dict)
                    content = line.get("content", "")
                    if not content:
                        continue
                    full_text_lines.append(content)
                    polygon = line.get("polygon")
                    bounding_box = (
                        [float(v) for v in polygon]
                        if polygon and isinstance(polygon, list)
                        else None
                    )
                    text_blocks.append(
                        OCRTextBlock(
                            text=content,
                            page_number=page_number,
                            bounding_box=bounding_box,
                            confidence=None,
                            metadata={"source": "azure_di_line"},
                        )
                    )

        full_text = "\n".join(full_text_lines)

        # Average confidence from pages if available
        page_confidences = [
            float(p["confidence"])
            for p in pages
            if isinstance(p, dict) and isinstance(p.get("confidence"), (int, float))
        ]
        avg_confidence = (
            sum(page_confidences) / len(page_confidences) if page_confidences else None
        )

        prebuilt_extraction: dict[str, object] | None = None
        if self.model_id == "prebuilt-invoice":
            prebuilt_extraction = self._parse_prebuilt_invoice_fields(
                result_payload=result_payload,
            )

        metadata: dict[str, object] = {
            "artifact_uri": input_data.artifact_uri,
            "content_hash": input_data.content_hash,
            "local_path": input_data.local_path,
            "tenant_id": str(context.tenant_id),
            "document_id": str(context.document_id),
            "workflow_run_id": str(context.workflow_run_id)
            if context.workflow_run_id is not None
            else None,
            "model_id": self.model_id,
            "page_count": len(pages),
        }
        if prebuilt_extraction is not None:
            metadata["prebuilt_invoice_extraction"] = prebuilt_extraction

        return OCRResult(
            provider_name=self.name,
            provider_version=_API_VERSION,
            language=None,
            full_text=full_text,
            text_blocks=text_blocks,
            confidence=avg_confidence,
            metadata=metadata,
        )

    def _parse_prebuilt_invoice_fields(
        self,
        *,
        result_payload: dict[str, object],
    ) -> dict[str, object]:
        """Parse structured invoice fields from an Azure DI prebuilt-invoice response.

        Maps the ``analyzeResult.documents[0].fields`` dictionary returned by the
        ``prebuilt-invoice`` model into the three internal extraction-group contracts
        (metadata, table, totals) so that downstream LLM extraction agents can be
        skipped entirely.

        Returns a dict with keys ``metadata_group``, ``table_group``, and
        ``totals_group`` — all ready to be written into the workflow scratchpad.
        Returns an empty dict if no documents were found in the response.
        """
        # Safely handle if result_payload contains "analyzeResult" (for tests / nested inputs)
        inner_payload = result_payload.get("analyzeResult")
        if isinstance(inner_payload, dict):
            payload = inner_payload
        else:
            payload = result_payload

        documents = payload.get("documents")
        if not isinstance(documents, list) or not documents:
            return {}

        doc = documents[0]
        if not isinstance(doc, dict):
            return {}

        fields = doc.get("fields")
        if not isinstance(fields, dict):
            return {}

        def _str(field_name: str) -> str | None:
            """Extract a string value from an Azure DI field object."""
            field = fields.get(field_name)
            if not isinstance(field, dict):
                return None
            # Prefer explicit string representation
            value = field.get("valueString") or field.get("content")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        def _date(field_name: str) -> str | None:
            """Extract an ISO date string from an Azure DI date field."""
            field = fields.get(field_name)
            if not isinstance(field, dict):
                return None
            value = field.get("valueDate") or field.get("content")
            if isinstance(value, str) and value.strip():
                return value.strip()
            return None

        def _currency_amount(field_name: str) -> str | None:
            """Extract a formatted decimal string from a currency field."""
            field = fields.get(field_name)
            if not isinstance(field, dict):
                return None
            currency_obj = field.get("valueCurrency")
            if isinstance(currency_obj, dict):
                amount = currency_obj.get("amount")
                if isinstance(amount, int | float):
                    return f"{amount:.2f}"
            # Fallback: try raw content
            content = field.get("content")
            if isinstance(content, str) and content.strip():
                cleaned = content.strip().lstrip("$€£¥").replace(",", "")
                try:
                    return f"{float(cleaned):.2f}"
                except ValueError:
                    return content.strip()
            return None

        def _currency_code(field_name: str) -> str | None:
            """Extract ISO currency code from a currency field."""
            field = fields.get(field_name)
            if not isinstance(field, dict):
                return None
            currency_obj = field.get("valueCurrency")
            if isinstance(currency_obj, dict):
                code = currency_obj.get("currencyCode")
                if isinstance(code, str) and code.strip():
                    return code.strip()
                symbol = currency_obj.get("currencySymbol")
                if isinstance(symbol, str):
                    # Map common symbols to ISO codes
                    _SYMBOL_MAP = {"$": "USD", "€": "EUR", "£": "GBP", "¥": "JPY"}
                    return _SYMBOL_MAP.get(symbol.strip())
            return None

        # ── Metadata group ────────────────────────────────────────────────────
        # Derive currency from whichever amount field is available first
        currency = (
            _currency_code("InvoiceTotal")
            or _currency_code("SubTotal")
            or _currency_code("TotalTax")
            or _currency_code("AmountDue")
        )

        metadata_group: dict[str, object] = {
            "schema_version": "invoice-metadata-group.v1",
            "extraction_status": "extracted",
            "invoice_number": _str("InvoiceId"),
            "supplier_name": _str("VendorName"),
            "supplier_tax_id": _str("VendorTaxId"),
            "customer_name": _str("CustomerName") or _str("CustomerAddressRecipient"),
            "customer_tax_id": _str("CustomerId"),
            "issue_date": _date("InvoiceDate"),
            "due_date": _date("DueDate"),
            "currency": currency,
            "evidence_refs": ["azure_di:prebuilt-invoice"],
            "confidence": "high",
        }

        # ── Table group (line items) ───────────────────────────────────────────
        items_field = fields.get("Items")
        line_items: list[dict[str, object]] = []
        if isinstance(items_field, dict):
            items_array = items_field.get("valueArray")
            if isinstance(items_array, list):
                for idx, item_entry in enumerate(items_array, start=1):
                    if not isinstance(item_entry, dict):
                        continue
                    item_fields = item_entry.get("valueObject")
                    if not isinstance(item_fields, dict):
                        continue

                    def _item_str(name: str) -> str | None:
                        f = item_fields.get(name)
                        if not isinstance(f, dict):
                            return None
                        v = f.get("valueString") or f.get("content")
                        return v.strip() if isinstance(v, str) and v.strip() else None

                    def _item_currency(name: str) -> str | None:
                        f = item_fields.get(name)
                        if not isinstance(f, dict):
                            return None
                        obj = f.get("valueCurrency")
                        if isinstance(obj, dict):
                            amt = obj.get("amount")
                            if isinstance(amt, int | float):
                                return f"{amt:.2f}"
                        content = f.get("content")
                        if isinstance(content, str):
                            cleaned = content.strip().lstrip("$€£¥").replace(",", "")
                            try:
                                return f"{float(cleaned):.2f}"
                            except ValueError:
                                return content.strip()
                        return None

                    def _item_number(name: str) -> str | None:
                        f = item_fields.get(name)
                        if not isinstance(f, dict):
                            return None
                        v = (
                            f.get("valueNumber")
                            or f.get("valueString")
                            or f.get("content")
                        )
                        if isinstance(v, int | float):
                            return str(v)
                        if isinstance(v, str) and v.strip():
                            return v.strip()
                        return None

                    line_items.append(
                        {
                            "line_number": idx,
                            "description": _item_str("Description"),
                            "quantity": _item_number("Quantity"),
                            "unit_price": _item_currency("UnitPrice"),
                            "tax_amount": _item_currency("Tax"),
                            "line_total": _item_currency("Amount"),
                            "evidence_refs": [f"azure_di:prebuilt-invoice:item:{idx}"],
                            "confidence": "high",
                        }
                    )

        table_group: dict[str, object] = {
            "schema_version": "invoice-table-group.v1",
            "extraction_status": "extracted" if line_items else "placeholder",
            "line_items": line_items,
            "table_region_ref": "azure_di:prebuilt-invoice:Items",
            "evidence_refs": ["azure_di:prebuilt-invoice"],
            "confidence": "high" if line_items else "unknown",
        }

        # ── Totals group ──────────────────────────────────────────────────────
        subtotal = _currency_amount("SubTotal")
        tax_amount = _currency_amount("TotalTax")
        total_amount = _currency_amount("InvoiceTotal") or _currency_amount("AmountDue")

        # Financial plausibility check: total_amount must be >= subtotal_amount.
        # If this constraint is violated (e.g. due to a stamp or smudge obscuring
        # the amount on the document), Azure DI may return a corrupted value such as
        # "0.419" for a total that is actually "419".  Downgrade confidence to "low"
        # so that is_scratchpad_group_populated() refuses the fast-path and the LLM
        # is invoked to reason about the correct total from the raw text.
        totals_confidence: str
        totals_status: str
        if total_amount is not None and subtotal is not None:
            try:
                total_float = float(total_amount)
                subtotal_float = float(subtotal)
                if subtotal_float > 0 and total_float < subtotal_float:
                    # Physically impossible: total cannot be less than subtotal
                    totals_confidence = "low"
                    totals_status = "low_confidence"
                else:
                    totals_confidence = "high"
                    totals_status = "extracted"
            except ValueError:
                totals_confidence = "high"
                totals_status = "extracted"
        elif any(v is not None for v in (subtotal, tax_amount, total_amount)):
            totals_confidence = "medium" if total_amount is None else "high"
            totals_status = "extracted"
        else:
            totals_confidence = "unknown"
            totals_status = "placeholder"

        totals_group: dict[str, object] = {
            "schema_version": "invoice-totals-group.v1",
            "extraction_status": totals_status,
            "subtotal_amount": subtotal,
            "tax_amount": tax_amount,
            "total_amount": total_amount,
            "currency": currency,
            "evidence_refs": ["azure_di:prebuilt-invoice"],
            "confidence": totals_confidence,
        }

        return {
            "metadata_group": metadata_group,
            "table_group": table_group,
            "totals_group": totals_group,
        }
