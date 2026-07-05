"""Image preprocessing pipeline for improving OCR accuracy on real-world documents.

This module provides an :class:`ImagePreprocessingConfig` dataclass and the
:func:`preprocess_image_for_ocr` function that applies a chain of classical
computer-vision operations to an input image before it is handed off to any
OCR engine.

It also provides :class:`PreprocessingOCRProvider`, a transparent decorator
that wraps any existing :class:`OCRProvider` and automatically runs the
preprocessing pipeline on the input image before delegating to the wrapped
provider.  The preprocessed copy is written to a temporary file that is cleaned
up immediately after OCR completes.

Requires ``opencv-python-headless`` to be installed.  It is optional; when it is
absent the module loads successfully but :func:`preprocess_image_for_ocr` raises
:class:`ProviderDependencyError` at call-time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.providers.errors import ProviderDependencyError
from app.providers.ocr import OCRInput, OCRProvider, OCRProviderRunContext, OCRResult

log = logging.getLogger(__name__)


def _unlink_if_exists(path: str) -> None:
    try:
        os.remove(path)
    except FileNotFoundError:
        pass


# ── Configuration ─────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ImagePreprocessingConfig:
    """Knobs that control which preprocessing steps are applied and how.

    Individual steps can be disabled for debugging or performance tuning
    without touching code.
    """

    enabled: bool = True

    # ── Upscaling ──────────────────────────────────────────────────────────
    upscale_min_px: int = 0
    """Up-scale the image when neither dimension exceeds this value (px).
    Larger images feed more detail to OCR models.  Set to 0 to disable."""

    upscale_factor: float = 2.0
    """Multiplier used when up-scaling is triggered."""

    # ── Contrast Enhancement ───────────────────────────────────────────────
    clahe_clip_limit: float = 2.0
    """Clip limit for CLAHE (Contrast Limited Adaptive Histogram Equalisation).
    Higher values produce stronger contrast.  Typical range: 1.0 – 4.0."""

    clahe_tile_grid_size: int = 8
    """Grid tile size for CLAHE.  Must be a positive integer."""

    # ── Binarisation ──────────────────────────────────────────────────────
    binarize: bool = False
    """Convert the image to binary (black/white) using adaptive thresholding."""

    binarize_block_size: int = 31
    """Neighbourhood size for adaptive threshold.  Must be odd and > 1."""

    binarize_c: int = 10
    """Constant subtracted from the mean in adaptive thresholding."""

    # ── Denoising ─────────────────────────────────────────────────────────
    denoise: bool = False
    """Remove salt-and-pepper noise with non-local means denoising."""

    denoise_h: float = 10.0

    """Filter strength for denoising.  Higher → stronger but may blur details."""

    # ── Deskewing ─────────────────────────────────────────────────────────
    deskew: bool = True
    """Detect and correct rotation using Hough line transform."""

    deskew_max_angle: float = 10.0
    """Maximum rotation angle (degrees) that will be corrected.  Larger
    rotations are likely to be intentional layout choices, not scan artefacts.
    """

    # ── Output format ─────────────────────────────────────────────────────
    output_suffix: str = "_preprocessed"
    """Suffix appended to the temp file name for easy identification in logs."""


# ── Core pipeline ─────────────────────────────────────────────────────────────


def preprocess_image_for_ocr(
    input_path: str,
    config: ImagePreprocessingConfig,
    *,
    output_path: str | None = None,
) -> str:
    """Run the preprocessing pipeline and return the path to the output image.

    Parameters
    ----------
    input_path:
        Absolute path to the original image (PNG/JPEG) or a single-page TIFF.
    config:
        Preprocessing configuration knobs.
    output_path:
        Optional explicit destination path.  When *None* a temporary file is
        created next to *input_path*.  The caller is responsible for deleting
        the file when it is no longer needed.

    Returns
    -------
    str
        Absolute path to the preprocessed image file.

    Raises
    ------
    ProviderDependencyError
        When ``opencv-python-headless`` or ``Pillow`` are not installed.
    """

    try:
        import cv2
    except ImportError as exc:
        raise ProviderDependencyError(
            "opencv-python-headless is required for OCR preprocessing. "
            "Install it with: pip install opencv-python-headless"
        ) from exc

    if not config.enabled:
        return input_path

    src = Path(input_path)
    log.debug("Preprocessing image for OCR: %s", src.name)

    # ── Load ──────────────────────────────────────────────────────────────
    img = cv2.imread(str(src))
    if img is None:
        log.warning("cv2.imread returned None for %s; skipping preprocessing", src)
        return input_path

    # ── Upscale ───────────────────────────────────────────────────────────
    if config.upscale_min_px > 0:
        h, w = img.shape[:2]
        if max(h, w) < config.upscale_min_px:
            factor = config.upscale_factor
            img = cv2.resize(
                img,
                (int(w * factor), int(h * factor)),
                interpolation=cv2.INTER_CUBIC,
            )
            log.debug("Upscaled image %.1fx to %dx%d", factor, *img.shape[:2][::-1])

    # ── Convert to greyscale ──────────────────────────────────────────────
    grey = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # ── CLAHE contrast enhancement ────────────────────────────────────────
    tile = config.clahe_tile_grid_size
    clahe = cv2.createCLAHE(
        clipLimit=config.clahe_clip_limit,
        tileGridSize=(tile, tile),
    )
    grey = clahe.apply(grey)
    log.debug("Applied CLAHE (clip=%.1f, tile=%d)", config.clahe_clip_limit, tile)

    # ── Denoising ────────────────────────────────────────────────────────
    if config.denoise:
        grey = cv2.fastNlMeansDenoising(
            grey,
            h=config.denoise_h,
        )
        log.debug("Applied NlMeansDenoising (h=%.1f)", config.denoise_h)

    # ── Deskewing ────────────────────────────────────────────────────────
    if config.deskew:
        grey = _deskew(grey, config.deskew_max_angle)

    # ── Adaptive binarisation ────────────────────────────────────────────
    if config.binarize:
        block = config.binarize_block_size
        # Ensure block size is odd and at least 3
        if block % 2 == 0:
            block += 1
        block = max(block, 3)
        grey = cv2.adaptiveThreshold(
            grey,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            block,
            config.binarize_c,
        )
        log.debug(
            "Applied adaptive threshold (block=%d, C=%d)",
            block,
            config.binarize_c,
        )

    # ── Write output ─────────────────────────────────────────────────────
    if output_path is None:
        stem = src.stem + config.output_suffix
        output_path = str(src.parent / f"{stem}{src.suffix}")

    ok = cv2.imwrite(output_path, grey)
    if not ok:
        log.warning("cv2.imwrite failed for %s; falling back to original", output_path)
        return input_path

    log.info(
        "Preprocessing complete: %s → %s",
        src.name,
        Path(output_path).name,
    )
    return output_path


# ── Helpers ───────────────────────────────────────────────────────────────────


def _deskew(grey: Any, max_angle: float) -> Any:
    """Return a deskewed copy of *grey* using the Hough line transform.

    If the detected rotation angle exceeds *max_angle* we assume it is an
    intentional layout choice and skip the correction.  This prevents
    accidental rotation of portrait→landscape documents.
    """
    import cv2
    import numpy

    # Detect edges to find prominent lines
    edges = cv2.Canny(grey, 50, 150, apertureSize=3)
    lines = cv2.HoughLinesP(
        edges,
        rho=1,
        theta=3.14159265 / 180,
        threshold=100,
        minLineLength=100,
        maxLineGap=10,
    )
    if lines is None or len(lines) == 0:
        return grey

    angles = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        if x2 - x1 == 0:
            continue
        angle = float(numpy.degrees(numpy.arctan2(y2 - y1, x2 - x1)))
        if abs(angle) < max_angle:
            angles.append(angle)

    if not angles:
        return grey

    median_angle = float(numpy.median(angles))
    log.debug("Deskew detected angle: %.2f°", median_angle)

    if abs(median_angle) < 0.3:
        return grey  # no meaningful skew detected

    h, w = grey.shape[:2]
    center = (w // 2, h // 2)
    rot_matrix = cv2.getRotationMatrix2D(center, median_angle, 1.0)
    return cv2.warpAffine(
        grey,
        rot_matrix,
        (w, h),
        flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_REPLICATE,
    )


# ── Decorator OCR Provider ────────────────────────────────────────────────────


class PreprocessingOCRProvider:
    """Transparent decorator that runs image preprocessing before delegating to
    an inner :class:`OCRProvider`.

    The wrapper is invisible to the rest of the system: it satisfies the same
    interface and passes all metadata through unchanged, only substituting the
    ``local_path`` on the :class:`OCRInput` with the preprocessed copy.

    The temporary preprocessed file is deleted immediately after the inner
    provider returns (or raises), so no disk space accumulates.
    """

    def __init__(
        self,
        inner: OCRProvider,
        config: ImagePreprocessingConfig,
    ) -> None:
        self._inner = inner
        self._config = config

    @property
    def name(self) -> str:
        """Return the name of the wrapped provider to satisfy routing validation."""
        return self._inner.name

    async def extract_text(
        self,
        *,
        input_data: OCRInput,
        context: OCRProviderRunContext,
    ) -> OCRResult:
        """Preprocess the input image then delegate to the wrapped provider."""

        if not self._config.enabled or not input_data.local_path:
            # Preprocessing disabled or no local file → pass through directly
            return await self._inner.extract_text(
                input_data=input_data,
                context=context,
            )

        preprocessed_path: str | None = None
        try:
            preprocessed_path = await _run_preprocessing(
                input_path=input_data.local_path,
                config=self._config,
            )

            preprocessing_applied = preprocessed_path != input_data.local_path
            modified_input = input_data
            if preprocessing_applied:
                modified_input = OCRInput(
                    local_path=preprocessed_path,
                    artifact_uri=input_data.artifact_uri,
                    content_hash=input_data.content_hash,
                    media_type=input_data.media_type,
                )
            result = await self._inner.extract_text(
                input_data=modified_input,
                context=context,
            )
            # Surface the true provider name so diagnostics remain accurate
            return OCRResult(
                provider_name=self._inner.name,
                language=result.language,
                full_text=result.full_text,
                text_blocks=result.text_blocks,
                confidence=result.confidence,
                metadata={
                    **result.metadata,
                    "preprocessing_applied": preprocessing_applied,
                    "preprocessing_wrapper": self.name,
                },
            )
        except ProviderDependencyError:
            # opencv not installed → fall back gracefully
            log.warning(
                "Image preprocessing skipped (dependency missing); "
                "falling back to raw OCR input."
            )
            return await self._inner.extract_text(
                input_data=input_data,
                context=context,
            )
        finally:
            # Always clean up the temp file, even on error
            if preprocessed_path and preprocessed_path != input_data.local_path:
                try:
                    os.remove(preprocessed_path)
                except OSError:
                    pass


async def _run_preprocessing(
    input_path: str,
    config: ImagePreprocessingConfig,
) -> str:
    """Run :func:`preprocess_image_for_ocr` in a thread pool."""

    suffix = Path(input_path).suffix or ".png"
    with tempfile.NamedTemporaryFile(
        suffix=suffix,
        delete=False,
        prefix="sme_ocr_prep_",
    ) as tmp:
        tmp_path = tmp.name

    try:
        result = await asyncio.to_thread(
            preprocess_image_for_ocr,
            input_path,
            config,
            output_path=tmp_path,
        )
    except Exception:
        await asyncio.to_thread(_unlink_if_exists, tmp_path)
        raise

    if result == input_path:
        await asyncio.to_thread(_unlink_if_exists, tmp_path)

    return result
