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
from app.providers.mock import (
    DEFAULT_MOCK_OCR_TEXT,
    DEFAULT_STRUCTURED_OUTPUTS,
    MOCK_PROVIDER_VERSION,
    MockLLMProvider,
    MockOCRProvider,
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
    "DEFAULT_MOCK_OCR_TEXT",
    "DEFAULT_STRUCTURED_OUTPUTS",
    "MOCK_PROVIDER_VERSION",
    "MockLLMProvider",
    "MockOCRProvider",
    "OCRInput",
    "OCRProvider",
    "OCRProviderRunContext",
    "OCRResult",
    "OCRTextBlock",
]
