from unittest.mock import MagicMock

from app.core.config import LLMProviderType, OCRProviderType, Settings
from app.jobs import ProcessingProfile
from app.workflows.job_executor import DocumentProcessingWorkflowExecutor


def build_executor() -> DocumentProcessingWorkflowExecutor:
    return DocumentProcessingWorkflowExecutor(
        session_factory=MagicMock(),
        settings=Settings(),
        storage=MagicMock(),
    )


def test_local_profile_uses_paddleocr_and_ollama() -> None:
    settings = build_executor()._settings_for_profile(ProcessingProfile.LOCAL)

    assert settings.ocr_provider == OCRProviderType.PADDLEOCR
    assert settings.llm_provider == LLMProviderType.OLLAMA
    assert settings.provider_allow_cloud is False


def test_hybrid_profile_uses_azure_layout_and_ollama() -> None:
    settings = build_executor()._settings_for_profile(ProcessingProfile.HYBRID)

    assert settings.ocr_provider == OCRProviderType.AZURE_DI
    assert settings.azure_di_model_id == "prebuilt-layout"
    assert settings.llm_provider == LLMProviderType.OLLAMA


def test_azure_profile_uses_prebuilt_invoice() -> None:
    settings = build_executor()._settings_for_profile(ProcessingProfile.AZURE)

    assert settings.ocr_provider == OCRProviderType.AZURE_DI
    assert settings.azure_di_model_id == "prebuilt-invoice"
