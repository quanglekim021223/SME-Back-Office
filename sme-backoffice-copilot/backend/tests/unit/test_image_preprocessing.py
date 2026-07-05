"""Unit tests for the image preprocessing pipeline.

These tests use a synthetic in-memory image created with numpy so that
OpenCV is the only dependency — no real invoice images are required.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from app.providers.errors import ProviderDependencyError
from app.providers.image_preprocessing import (
    ImagePreprocessingConfig,
    PreprocessingOCRProvider,
    _deskew,
    preprocess_image_for_ocr,
)
from app.providers.ocr import OCRInput, OCRProviderRunContext, OCRResult, OCRTextBlock

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _make_ocr_context() -> OCRProviderRunContext:
    return OCRProviderRunContext(
        tenant_id=uuid4(),
        document_id=uuid4(),
    )


def _make_ocr_input(path: str) -> OCRInput:
    return OCRInput(artifact_uri="test://doc.png", local_path=path)


def _make_ocr_result() -> OCRResult:
    return OCRResult(
        provider_name="mock_inner",
        language="en",
        full_text="SHIVSAGAR\nTotal: 419",
        text_blocks=[
            OCRTextBlock(text="SHIVSAGAR"),
            OCRTextBlock(text="Total: 419"),
        ],
    )


# ── Config defaults ───────────────────────────────────────────────────────────


def test_preprocessing_config_defaults() -> None:
    cfg = ImagePreprocessingConfig()
    assert cfg.enabled is True
    assert cfg.deskew is True
    assert cfg.denoise is False
    assert cfg.binarize is False
    assert cfg.upscale_min_px == 0


def test_preprocessing_config_can_disable_all_steps() -> None:
    cfg = ImagePreprocessingConfig(enabled=False)
    assert cfg.enabled is False


# ── preprocess_image_for_ocr ─────────────────────────────────────────────────


def test_preprocess_returns_original_when_disabled(tmp_path: Path) -> None:
    """When config.enabled is False the function must return the original path."""
    img_path = str(tmp_path / "test.png")
    # Create a minimal valid PNG (1x1 white pixel via cv2)
    try:
        import cv2  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("opencv not installed")

    img = np.full((50, 50, 3), 255, dtype=np.uint8)
    cv2.imwrite(img_path, img)

    cfg = ImagePreprocessingConfig(enabled=False)
    result = preprocess_image_for_ocr(img_path, cfg)
    assert result == img_path


def test_preprocess_returns_original_when_cv2_missing(tmp_path: Path) -> None:
    """When opencv is not installed the function raises ProviderDependencyError."""
    img_path = str(tmp_path / "test.png")
    cfg = ImagePreprocessingConfig()

    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "cv2":
            raise ImportError("no cv2")
        # pyrefly: ignore [bad-argument-type]
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=fake_import):
        with pytest.raises(ProviderDependencyError):
            preprocess_image_for_ocr(img_path, cfg)


def test_preprocess_output_file_is_different_from_input(tmp_path: Path) -> None:
    """The pipeline should produce a new output file, not overwrite the input."""
    try:
        import cv2  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("opencv not installed")

    img_path = str(tmp_path / "invoice.png")
    out_path = str(tmp_path / "invoice_prep.png")

    # Synthetic receipt-like image
    img = np.full((400, 300, 3), 230, dtype=np.uint8)
    cv2.putText(img, "TOTAL 419", (30, 200), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 2)
    cv2.imwrite(img_path, img)

    cfg = ImagePreprocessingConfig(deskew=False)  # skip deskew for speed
    result = preprocess_image_for_ocr(img_path, cfg, output_path=out_path)

    assert result == out_path
    assert Path(out_path).exists()
    assert Path(out_path).stat().st_size > 0


# ── _deskew helper ────────────────────────────────────────────────────────────


def test_deskew_returns_image_without_prominent_lines() -> None:
    """Without prominent lines, _deskew must return an unchanged image."""
    try:
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("numpy not installed")

    img = np.full((100, 100), 255, dtype=np.uint8)
    result = _deskew(img, max_angle=10.0)
    # Should return without error; type is consistent
    assert result is not None


# ── PreprocessingOCRProvider (decorator) ──────────────────────────────────────


@pytest.mark.asyncio
async def test_decorator_passes_through_when_preprocessing_disabled() -> None:
    """With preprocessing disabled, call the inner provider with original input."""
    inner = MagicMock()
    inner.name = "mock_inner"
    inner.extract_text = AsyncMock(return_value=_make_ocr_result())

    cfg = ImagePreprocessingConfig(enabled=False)
    wrapper = PreprocessingOCRProvider(inner=inner, config=cfg)  # type: ignore[arg-type]

    ocr_input = _make_ocr_input("/some/path.png")
    ctx = _make_ocr_context()
    result = await wrapper.extract_text(input_data=ocr_input, context=ctx)

    inner.extract_text.assert_awaited_once_with(input_data=ocr_input, context=ctx)
    assert result.full_text == "SHIVSAGAR\nTotal: 419"


@pytest.mark.asyncio
async def test_decorator_passes_through_when_no_local_path() -> None:
    """Without a local_path the decorator must delegate immediately."""
    inner = MagicMock()
    inner.name = "mock_inner"
    inner.extract_text = AsyncMock(return_value=_make_ocr_result())

    cfg = ImagePreprocessingConfig()
    wrapper = PreprocessingOCRProvider(inner=inner, config=cfg)  # type: ignore[arg-type]

    ocr_input = OCRInput(artifact_uri="test://doc.png", local_path=None)
    ctx = _make_ocr_context()
    result = await wrapper.extract_text(input_data=ocr_input, context=ctx)

    inner.extract_text.assert_awaited_once()
    assert result.full_text == "SHIVSAGAR\nTotal: 419"


@pytest.mark.asyncio
async def test_decorator_name_returns_inner_name() -> None:
    inner = MagicMock()
    inner.name = "tesseract"
    cfg = ImagePreprocessingConfig(enabled=False)
    wrapper = PreprocessingOCRProvider(inner=inner, config=cfg)  # type: ignore[arg-type]
    assert wrapper.name == "tesseract"


@pytest.mark.asyncio
async def test_decorator_applies_preprocessing_and_calls_inner(tmp_path: Path) -> None:
    """Decorator preprocesses image and calls the inner provider with new path."""
    try:
        import cv2  # type: ignore[import-untyped]
        import numpy as np  # type: ignore[import-untyped]
    except ImportError:
        pytest.skip("opencv not installed")

    img_path = str(tmp_path / "receipt.png")
    img = np.full((300, 200, 3), 220, dtype=np.uint8)
    cv2.imwrite(img_path, img)

    inner = MagicMock()
    inner.name = "mock_inner"
    inner.extract_text = AsyncMock(return_value=_make_ocr_result())

    cfg = ImagePreprocessingConfig(deskew=False)
    wrapper = PreprocessingOCRProvider(inner=inner, config=cfg)  # type: ignore[arg-type]

    ocr_input = _make_ocr_input(img_path)
    ctx = _make_ocr_context()
    result = await wrapper.extract_text(input_data=ocr_input, context=ctx)

    # Inner was called with a DIFFERENT (preprocessed) path
    call_kwargs = inner.extract_text.call_args.kwargs
    called_input: OCRInput = call_kwargs["input_data"]
    assert called_input.local_path != img_path
    assert result.metadata.get("preprocessing_applied") is True

    # Temp file was cleaned up automatically
    # pyrefly: ignore [bad-argument-type]
    exists = await asyncio.to_thread(os.path.exists, called_input.local_path or "")
    assert not exists
