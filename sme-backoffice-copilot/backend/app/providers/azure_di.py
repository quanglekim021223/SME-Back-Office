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
            sum(page_confidences) / len(page_confidences)
            if page_confidences
            else None
        )

        return OCRResult(
            provider_name=self.name,
            provider_version=_API_VERSION,
            language=None,
            full_text=full_text,
            text_blocks=text_blocks,
            confidence=avg_confidence,
            metadata={
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
            },
        )
