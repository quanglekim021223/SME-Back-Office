"""Provider contracts for OCR, LLM, and future external AI adapters."""

from app.providers.llm import (
    LLMGenerationRequest,
    LLMGenerationResult,
    LLMMessage,
    LLMMessageRole,
    LLMProvider,
    LLMProviderRunContext,
    LLMResponseFormat,
)
from app.providers.ocr import (
    OCRInput,
    OCRProvider,
    OCRProviderRunContext,
    OCRResult,
    OCRTextBlock,
)

__all__ = [
    "LLMGenerationRequest",
    "LLMGenerationResult",
    "LLMMessage",
    "LLMMessageRole",
    "LLMProvider",
    "LLMProviderRunContext",
    "LLMResponseFormat",
    "OCRInput",
    "OCRProvider",
    "OCRProviderRunContext",
    "OCRResult",
    "OCRTextBlock",
]
