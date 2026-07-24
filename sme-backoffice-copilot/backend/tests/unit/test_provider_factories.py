from decimal import Decimal

import pytest

from app.core.config import Settings
from app.providers import (
    ChandraOCRProvider,
    MockLLMProvider,
    MockOCRProvider,
    OllamaLLMProvider,
    OpenAIResponsesLLMProvider,
    PaddleOCRProvider,
    ProviderConfigurationError,
    ProviderDeploymentMode,
    ProviderTaskType,
    TesseractOCRProvider,
    build_llm_provider_from_settings,
    build_ocr_provider_from_settings,
    build_provider_privacy_gate_from_settings,
    build_provider_routing_config_from_settings,
)
from app.providers.azure_di import AzureDIOCRProvider
from app.providers.image_preprocessing import PreprocessingOCRProvider


def test_provider_factories_build_default_mock_providers() -> None:
    settings = Settings(_env_file=None)

    llm_provider = build_llm_provider_from_settings(settings)
    ocr_provider = build_ocr_provider_from_settings(settings)

    assert isinstance(llm_provider, MockLLMProvider)
    assert llm_provider.name == "mock_llm"
    assert isinstance(ocr_provider, MockOCRProvider)
    assert ocr_provider.name == "mock_ocr"


def test_provider_factories_build_local_ollama_and_tesseract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setenv("OCR_PROVIDER", "tesseract")
    monkeypatch.setenv("TESSERACT_BINARY_PATH", "/opt/homebrew/bin/tesseract")
    monkeypatch.setenv("TESSERACT_LANGUAGE", "eng+vie")
    monkeypatch.setenv("OCR_PREPROCESSING_ENABLED", "true")
    settings = Settings(_env_file=None)

    llm_provider = build_llm_provider_from_settings(settings)
    ocr_provider = build_ocr_provider_from_settings(settings)

    assert isinstance(llm_provider, OllamaLLMProvider)
    assert llm_provider.name == "ollama"
    assert llm_provider.model_name == "llama3.1:8b"
    # With preprocessing enabled, the OCR provider is wrapped
    assert isinstance(ocr_provider, PreprocessingOCRProvider)
    assert isinstance(ocr_provider._inner, TesseractOCRProvider)
    assert ocr_provider._inner.binary_path == "/opt/homebrew/bin/tesseract"
    assert ocr_provider._inner.language == "eng+vie"


def test_provider_factories_tesseract_unwrapped_when_preprocessing_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "tesseract")
    monkeypatch.setenv("OCR_PREPROCESSING_ENABLED", "false")
    settings = Settings(_env_file=None)

    ocr_provider = build_ocr_provider_from_settings(settings)

    # Without preprocessing the raw provider is returned directly
    assert isinstance(ocr_provider, TesseractOCRProvider)
    assert ocr_provider.name == "tesseract"


def test_provider_factories_wrap_azure_di_when_preprocessing_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "azure_di")
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://example.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_DI_KEY", "test-key")
    monkeypatch.setenv("OCR_PREPROCESSING_ENABLED", "true")
    settings = Settings(_env_file=None)

    provider = build_ocr_provider_from_settings(settings)

    assert isinstance(provider, PreprocessingOCRProvider)
    assert isinstance(provider._inner, AzureDIOCRProvider)


def test_provider_factories_leave_azure_di_unwrapped_when_preprocessing_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "azure_di")
    monkeypatch.setenv("AZURE_DI_ENDPOINT", "https://example.cognitiveservices.azure.com/")
    monkeypatch.setenv("AZURE_DI_KEY", "test-key")
    monkeypatch.setenv("OCR_PREPROCESSING_ENABLED", "false")
    settings = Settings(_env_file=None)

    provider = build_ocr_provider_from_settings(settings)

    assert isinstance(provider, AzureDIOCRProvider)


def test_provider_factories_build_local_optional_ocr_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OCR_PROVIDER", "paddleocr")
    monkeypatch.setenv("OCR_PREPROCESSING_ENABLED", "true")
    settings = Settings(_env_file=None)

    provider = build_ocr_provider_from_settings(settings)
    # Preprocessing wrapper is explicitly enabled; inner provider is PaddleOCR
    assert isinstance(provider, PreprocessingOCRProvider)
    assert isinstance(provider._inner, PaddleOCRProvider)

    monkeypatch.setenv("OCR_PROVIDER", "chandraocr")
    settings = Settings(_env_file=None)

    provider = build_ocr_provider_from_settings(settings)
    assert isinstance(provider, PreprocessingOCRProvider)
    assert isinstance(provider._inner, ChandraOCRProvider)


def test_provider_factories_build_openai_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://api.openai.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.2")
    settings = Settings(_env_file=None)

    provider = build_llm_provider_from_settings(settings)

    assert isinstance(provider, OpenAIResponsesLLMProvider)
    assert provider.name == "openai"
    assert provider.base_url == "https://api.openai.test/v1"
    assert provider.model_name == "gpt-5.2"


def test_provider_factories_require_openai_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "")
    settings = Settings(_env_file=None)

    with pytest.raises(ProviderConfigurationError):
        build_llm_provider_from_settings(settings)


def test_provider_routing_factory_uses_selected_local_providers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1:8b")
    monkeypatch.setenv("OCR_PROVIDER", "tesseract")
    monkeypatch.setenv("PROVIDER_TIMEOUT_SECONDS", "45")
    monkeypatch.setenv("PROVIDER_MAX_RETRIES", "2")
    monkeypatch.setenv("PROVIDER_RETRY_BACKOFF_SECONDS", "0.25")
    monkeypatch.setenv("LLM_INPUT_COST_PER_1K_TOKENS_USD", "0.001")
    monkeypatch.setenv("LLM_OUTPUT_COST_PER_1K_TOKENS_USD", "0.002")
    settings = Settings(_env_file=None)

    routing_config = build_provider_routing_config_from_settings(settings)
    ocr_route = routing_config.route_for(ProviderTaskType.DOCUMENT_OCR)
    llm_route = routing_config.route_for(ProviderTaskType.INVOICE_METADATA_EXTRACTION)

    assert routing_config.default_timeout_seconds == 45
    assert routing_config.default_max_retries == 2
    assert routing_config.default_retry_backoff_seconds == 0.25
    assert ocr_route.provider_name == "tesseract"
    assert ocr_route.deployment_mode == ProviderDeploymentMode.LOCAL
    assert llm_route.provider_name == "ollama"
    assert llm_route.model_name == "llama3.1:8b"
    assert llm_route.deployment_mode == ProviderDeploymentMode.LOCAL
    assert llm_route.input_cost_per_1k_tokens == Decimal("0.001")
    assert llm_route.output_cost_per_1k_tokens == Decimal("0.002")


def test_provider_routing_factory_marks_openai_as_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.2")
    settings = Settings(_env_file=None)

    routing_config = build_provider_routing_config_from_settings(settings)
    route = routing_config.route_for(ProviderTaskType.INVOICE_TOTALS_EXTRACTION)

    assert route.provider_name == "openai"
    assert route.model_name == "gpt-5.2"
    assert route.deployment_mode == ProviderDeploymentMode.CLOUD


def test_provider_privacy_gate_factory_uses_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PROVIDER_ALLOW_CLOUD", "true")
    monkeypatch.setenv("PROVIDER_ALLOW_SENSITIVE_CLOUD_PAYLOADS", "true")
    monkeypatch.setenv("PROVIDER_REQUIRE_DEIDENTIFIED_CLOUD_EVALUATION", "false")
    monkeypatch.setenv("PROVIDER_REDACTION_MAX_CHARS", "2048")
    settings = Settings(_env_file=None)

    gate = build_provider_privacy_gate_from_settings(settings)

    assert gate.policy.allow_cloud_providers is True
    assert gate.policy.allow_sensitive_cloud_payloads is True
    assert gate.policy.require_deidentified_for_cloud_evaluation is False
    assert gate.policy.max_provider_text_chars == 2048
