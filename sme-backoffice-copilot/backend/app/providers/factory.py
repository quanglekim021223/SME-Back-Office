"""Provider factories that translate application settings into runtime objects."""

from __future__ import annotations

from app.core.config import LLMProviderType, OCRProviderType, Settings
from app.providers.base import ProviderDeploymentMode
from app.providers.image_preprocessing import (
    ImagePreprocessingConfig,
    PreprocessingOCRProvider,
)
from app.providers.azure_di import AzureDIOCRProvider
from app.providers.llm import LLMProvider
from app.providers.local_ocr import (
    ChandraOCRProvider,
    PaddleOCRProvider,
    TesseractOCRProvider,
)
from app.providers.mock import MockLLMProvider, MockOCRProvider
from app.providers.ocr import OCRProvider
from app.providers.ollama import OllamaLLMProvider
from app.providers.openai import OpenAIResponsesLLMProvider
from app.providers.privacy import (
    ProviderPrivacyGate,
    build_provider_privacy_policy,
)
from app.providers.routing import (
    ProviderRoutingConfig,
    build_default_provider_routing_config,
)


def build_llm_provider_from_settings(settings: Settings) -> LLMProvider:
    """Build the selected LLM provider adapter from application settings."""

    match settings.llm_provider:
        case LLMProviderType.MOCK:
            return MockLLMProvider()
        case LLMProviderType.OLLAMA:
            return OllamaLLMProvider(
                base_url=settings.ollama_base_url,
                model_name=settings.ollama_model,
                timeout_seconds=settings.provider_timeout_seconds,
            )
        case LLMProviderType.OPENAI:
            return OpenAIResponsesLLMProvider(
                api_key=settings.openai_api_key,
                base_url=settings.openai_base_url,
                model_name=settings.openai_model,
                timeout_seconds=settings.provider_timeout_seconds,
            )


def build_ocr_provider_from_settings(settings: Settings) -> OCRProvider:
    """Build the selected OCR provider adapter from application settings.

    When ``ocr_preprocessing_enabled`` is *True* in settings, all real (non-mock)
    providers are wrapped in :class:`PreprocessingOCRProvider` so that images are
    automatically enhanced before OCR runs.
    """

    preprocessing_config = ImagePreprocessingConfig(
        enabled=settings.ocr_preprocessing_enabled,
        deskew=settings.ocr_preprocessing_deskew,
        denoise=settings.ocr_preprocessing_denoise,
        binarize=settings.ocr_preprocessing_binarize,
        upscale_min_px=settings.ocr_preprocessing_upscale_min_px,
        clahe_clip_limit=settings.ocr_preprocessing_clahe_clip_limit,
        clahe_tile_grid_size=settings.ocr_preprocessing_clahe_tile_grid_size,
    )

    match settings.ocr_provider:
        case OCRProviderType.MOCK:
            return MockOCRProvider()
        case OCRProviderType.TESSERACT:
            inner: OCRProvider = TesseractOCRProvider(
                binary_path=settings.tesseract_binary_path,
                language=settings.tesseract_language,
                timeout_seconds=settings.provider_timeout_seconds,
            )
        case OCRProviderType.PADDLEOCR:
            inner = PaddleOCRProvider(
                language=settings.paddleocr_language,
                timeout_seconds=settings.provider_timeout_seconds,
            )
        case OCRProviderType.CHANDRAOCR:
            inner = ChandraOCRProvider(
                language=settings.chandraocr_language,
                timeout_seconds=settings.provider_timeout_seconds,
            )
        case OCRProviderType.AZURE_DI:
            # Azure DI is a cloud service — it handles image preprocessing internally,
            # so we return it directly without wrapping in PreprocessingOCRProvider.
            return AzureDIOCRProvider(
                endpoint=settings.azure_di_endpoint,
                key=settings.azure_di_key,
                model_id=settings.azure_di_model_id,
                timeout_seconds=settings.provider_timeout_seconds,
            )

    if preprocessing_config.enabled:
        return PreprocessingOCRProvider(inner=inner, config=preprocessing_config)
    return inner


def build_provider_routing_config_from_settings(
    settings: Settings,
) -> ProviderRoutingConfig:
    """Build provider routing using the currently selected settings providers."""

    return build_default_provider_routing_config(
        llm_provider_name=llm_provider_name_from_settings(settings),
        llm_model_name=llm_model_name_from_settings(settings),
        ocr_provider_name=ocr_provider_name_from_settings(settings),
        llm_deployment_mode=llm_deployment_mode_from_settings(settings),
        ocr_deployment_mode=ocr_deployment_mode_from_settings(settings),
        timeout_seconds=settings.provider_timeout_seconds,
        max_retries=settings.provider_max_retries,
        retry_backoff_seconds=settings.provider_retry_backoff_seconds,
        llm_input_cost_per_1k_tokens=settings.llm_input_cost_per_1k_tokens_usd,
        llm_output_cost_per_1k_tokens=settings.llm_output_cost_per_1k_tokens_usd,
    )


def build_provider_privacy_gate_from_settings(
    settings: Settings,
) -> ProviderPrivacyGate:
    """Build provider privacy gate from application settings."""

    return ProviderPrivacyGate(
        build_provider_privacy_policy(
            allow_cloud_providers=settings.provider_allow_cloud,
            allow_sensitive_cloud_payloads=(
                settings.provider_allow_sensitive_cloud_payloads
            ),
            require_deidentified_for_cloud_evaluation=(
                settings.provider_require_deidentified_cloud_evaluation
            ),
            max_provider_text_chars=settings.provider_redaction_max_chars,
        )
    )


def llm_provider_name_from_settings(settings: Settings) -> str:
    """Return the stable provider name for selected LLM settings."""

    match settings.llm_provider:
        case LLMProviderType.MOCK:
            return "mock_llm"
        case LLMProviderType.OLLAMA:
            return "ollama"
        case LLMProviderType.OPENAI:
            return "openai"


def ocr_provider_name_from_settings(settings: Settings) -> str:
    """Return the stable provider name for selected OCR settings."""

    match settings.ocr_provider:
        case OCRProviderType.MOCK:
            return "mock_ocr"
        case OCRProviderType.TESSERACT:
            return "tesseract"
        case OCRProviderType.PADDLEOCR:
            return "paddleocr"
        case OCRProviderType.CHANDRAOCR:
            return "chandraocr"
        case OCRProviderType.AZURE_DI:
            return "azure_di"


def llm_model_name_from_settings(settings: Settings) -> str:
    """Return selected LLM model name for routing metadata."""

    match settings.llm_provider:
        case LLMProviderType.MOCK:
            return "mock-llm"
        case LLMProviderType.OLLAMA:
            return settings.ollama_model
        case LLMProviderType.OPENAI:
            return settings.openai_model


def llm_deployment_mode_from_settings(settings: Settings) -> ProviderDeploymentMode:
    """Return deployment mode for the selected LLM provider."""

    match settings.llm_provider:
        case LLMProviderType.MOCK:
            return ProviderDeploymentMode.MOCK
        case LLMProviderType.OLLAMA:
            return ProviderDeploymentMode.LOCAL
        case LLMProviderType.OPENAI:
            return ProviderDeploymentMode.CLOUD


def ocr_deployment_mode_from_settings(settings: Settings) -> ProviderDeploymentMode:
    """Return deployment mode for the selected OCR provider."""

    match settings.ocr_provider:
        case OCRProviderType.MOCK:
            return ProviderDeploymentMode.MOCK
        case (
            OCRProviderType.TESSERACT
            | OCRProviderType.PADDLEOCR
            | OCRProviderType.CHANDRAOCR
        ):
            return ProviderDeploymentMode.LOCAL
        case OCRProviderType.AZURE_DI:
            return ProviderDeploymentMode.CLOUD
