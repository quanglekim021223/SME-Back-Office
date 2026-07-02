"""Optional local OCR provider adapters for Tesseract and PaddleOCR."""

from __future__ import annotations

import asyncio
import importlib
import subprocess
from collections.abc import Callable, Sequence
from subprocess import CompletedProcess
from typing import cast

from app.providers.errors import (
    ProviderConfigurationError,
    ProviderDependencyError,
    ProviderExecutionError,
)
from app.providers.ocr import (
    OCRInput,
    OCRProviderRunContext,
    OCRResult,
    OCRTextBlock,
)

SubprocessRunner = Callable[[Sequence[str], float], CompletedProcess[str]]


def run_subprocess(
    command: Sequence[str],
    timeout_seconds: float,
) -> CompletedProcess[str]:
    """Run a local command and capture text output."""

    return subprocess.run(
        list(command),
        capture_output=True,
        check=False,
        text=True,
        timeout=timeout_seconds,
    )


class TesseractOCRProvider:
    """OCR provider adapter backed by the local Tesseract command-line binary."""

    def __init__(
        self,
        *,
        binary_path: str = "tesseract",
        language: str = "eng",
        timeout_seconds: float = 30.0,
        runner: SubprocessRunner = run_subprocess,
    ) -> None:
        self.binary_path = binary_path
        self.language = language
        self.timeout_seconds = timeout_seconds
        self.runner = runner

    @property
    def name(self) -> str:
        """Return the stable Tesseract provider name."""

        return "tesseract"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Extract text from a local image path using the Tesseract binary."""

        if not input_data.local_path:
            raise ProviderConfigurationError(
                "TesseractOCRProvider requires OCRInput.local_path."
            )

        command = [
            self.binary_path,
            input_data.local_path,
            "stdout",
            "-l",
            self.language,
        ]
        try:
            completed = await asyncio.to_thread(
                self.runner,
                command,
                self.timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise ProviderDependencyError(
                f"Tesseract binary was not found: {self.binary_path}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ProviderExecutionError(
                f"Tesseract timed out after {self.timeout_seconds} seconds."
            ) from exc

        if completed.returncode != 0:
            raise ProviderExecutionError(
                "Tesseract OCR failed: "
                f"{completed.stderr.strip() or 'no stderr output'}"
            )

        full_text = completed.stdout.strip()
        return OCRResult(
            provider_name=self.name,
            language=self.language,
            full_text=full_text,
            text_blocks=create_line_text_blocks(
                full_text=full_text,
                source=self.name,
            ),
            metadata={
                "artifact_uri": input_data.artifact_uri,
                "content_hash": input_data.content_hash,
                "local_path": input_data.local_path,
                "tenant_id": str(context.tenant_id),
                "document_id": str(context.document_id),
                "workflow_run_id": str(context.workflow_run_id)
                if context.workflow_run_id is not None
                else None,
                "correlation_id": context.correlation_id,
                "command": command,
            },
        )


class PaddleOCRProvider:
    """OCR provider adapter backed by the optional local PaddleOCR package."""

    def __init__(
        self,
        *,
        language: str = "en",
        timeout_seconds: float = 30.0,
        engine: object | None = None,
    ) -> None:
        self.language = language
        self.timeout_seconds = timeout_seconds
        self._engine = engine

    @property
    def name(self) -> str:
        """Return the stable PaddleOCR provider name."""

        return "paddleocr"

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Extract text from a local image/PDF path using PaddleOCR."""

        if not input_data.local_path:
            raise ProviderConfigurationError(
                "PaddleOCRProvider requires OCRInput.local_path."
            )

        try:
            raw_output = await asyncio.wait_for(
                asyncio.to_thread(self._run_engine, input_data.local_path),
                timeout=self.timeout_seconds,
            )
        except TimeoutError as exc:
            raise ProviderExecutionError(
                f"PaddleOCR timed out after {self.timeout_seconds} seconds."
            ) from exc

        text_blocks = normalize_paddleocr_text_blocks(raw_output)
        full_text = "\n".join(block.text for block in text_blocks)
        return OCRResult(
            provider_name=self.name,
            language=self.language,
            full_text=full_text,
            text_blocks=text_blocks,
            confidence=average_confidence(text_blocks),
            metadata={
                "artifact_uri": input_data.artifact_uri,
                "content_hash": input_data.content_hash,
                "local_path": input_data.local_path,
                "tenant_id": str(context.tenant_id),
                "document_id": str(context.document_id),
                "workflow_run_id": str(context.workflow_run_id)
                if context.workflow_run_id is not None
                else None,
                "correlation_id": context.correlation_id,
            },
        )

    def _run_engine(self, local_path: str) -> object:
        """Run the injected or lazily-created PaddleOCR engine."""

        engine = self._engine or self._load_engine()
        ocr_method = getattr(engine, "ocr", None)
        if not callable(ocr_method):
            raise ProviderExecutionError("PaddleOCR engine does not expose ocr().")
        return cast(Callable[[str], object], ocr_method)(local_path)

    def _load_engine(self) -> object:
        """Create a PaddleOCR engine only when the adapter is actually used."""

        try:
            paddleocr_module = importlib.import_module("paddleocr")
        except ImportError as exc:
            raise ProviderDependencyError(
                "PaddleOCR is not installed. Install optional local OCR "
                "dependencies before selecting OCR_PROVIDER=paddleocr."
            ) from exc

        paddleocr_class = getattr(paddleocr_module, "PaddleOCR", None)
        if paddleocr_class is None:
            raise ProviderDependencyError(
                "The installed paddleocr package does not expose PaddleOCR."
            )
        self._engine = cast(Callable[..., object], paddleocr_class)(
            lang=self.language,
        )
        return self._engine


def create_line_text_blocks(
    *,
    full_text: str,
    source: str,
) -> list[OCRTextBlock]:
    """Create one OCR text block per non-empty text line."""

    return [
        OCRTextBlock(
            text=line,
            page_number=1,
            metadata={"source": source, "line_index": index},
        )
        for index, line in enumerate(full_text.splitlines(), start=1)
        if line.strip()
    ]


def normalize_paddleocr_text_blocks(raw_output: object) -> list[OCRTextBlock]:
    """Normalize common PaddleOCR output shapes into OCRTextBlock objects."""

    blocks: list[OCRTextBlock] = []
    for index, candidate in enumerate(
        iter_paddleocr_line_candidates(raw_output), start=1
    ):
        block = paddleocr_candidate_to_text_block(candidate, index)
        if block is not None:
            blocks.append(block)
    return blocks


def iter_paddleocr_line_candidates(value: object) -> list[Sequence[object]]:
    """Return candidate line records from nested PaddleOCR output."""

    candidates: list[Sequence[object]] = []
    if isinstance(value, list | tuple):
        if looks_like_paddleocr_line(value):
            candidates.append(value)
            return candidates
        for item in value:
            candidates.extend(iter_paddleocr_line_candidates(item))
    return candidates


def looks_like_paddleocr_line(value: Sequence[object]) -> bool:
    """Return true when a sequence looks like a PaddleOCR text line."""

    if len(value) < 2:
        return False
    return extract_text_and_confidence(value[1]) is not None


def paddleocr_candidate_to_text_block(
    candidate: Sequence[object],
    line_index: int,
) -> OCRTextBlock | None:
    """Convert one PaddleOCR candidate line into a text block."""

    text_and_confidence = extract_text_and_confidence(candidate[1])
    if text_and_confidence is None:
        return None
    text, confidence = text_and_confidence
    if not text.strip():
        return None
    return OCRTextBlock(
        text=text,
        page_number=1,
        bounding_box=flatten_numeric_values(candidate[0]),
        confidence=normalize_confidence(confidence),
        metadata={"source": "paddleocr", "line_index": line_index},
    )


def extract_text_and_confidence(value: object) -> tuple[str, float | None] | None:
    """Extract text and confidence from common PaddleOCR line payloads."""

    if isinstance(value, str):
        return value, None
    if isinstance(value, dict):
        text = value.get("text")
        confidence = value.get("confidence") or value.get("score")
        if isinstance(text, str):
            return text, confidence if isinstance(confidence, int | float) else None
    if isinstance(value, list | tuple) and value and isinstance(value[0], str):
        confidence = value[1] if len(value) > 1 else None
        return value[0], confidence if isinstance(confidence, int | float) else None
    return None


def flatten_numeric_values(value: object) -> list[float] | None:
    """Flatten nested numeric coordinate values into a single list."""

    flattened: list[float] = []

    def collect(item: object) -> None:
        if isinstance(item, int | float):
            flattened.append(float(item))
        elif isinstance(item, list | tuple):
            for nested_item in item:
                collect(nested_item)

    collect(value)
    return flattened or None


def normalize_confidence(confidence: float | None) -> float | None:
    """Normalize confidence values to the 0..1 range when possible."""

    if confidence is None:
        return None
    if 0.0 <= confidence <= 1.0:
        return confidence
    if 1.0 < confidence <= 100.0:
        return confidence / 100.0
    return None


def average_confidence(text_blocks: list[OCRTextBlock]) -> float | None:
    """Return average text-block confidence when all blocks provide it."""

    confidences = [
        block.confidence for block in text_blocks if block.confidence is not None
    ]
    if not confidences:
        return None
    return sum(confidences) / len(confidences)
