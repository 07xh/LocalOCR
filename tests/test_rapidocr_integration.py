"""Actual model-inference acceptance, enabled in dedicated CI by environment variable.

This must not be confused with unit tests of a fake RapidOCR output adapter.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

from localocr.engine import OCRService

pytestmark = pytest.mark.skipif(
    os.environ.get("LOCALOCR_REAL_RAPID") != "1",
    reason="Real model inference requires the dedicated RapidOCR CI environment",
)


def _font(size: int) -> ImageFont.FreeTypeFont:
    candidates = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "C:/Windows/Fonts/arial.ttf",
    )
    file = next((p for p in candidates if Path(p).is_file()), None)
    if not file:
        pytest.skip("No suitable system font for actual OCR test image")
    return ImageFont.truetype(file, size)


def test_real_rapidocr_english_model_and_warm_reuse():
    assert OCRService.backends()["rapidocr"], "RapidOCR + ONNX Runtime must be installed"
    image = Image.new("RGB", (920, 190), "white")
    ImageDraw.Draw(image).text((32, 36), "HELLO 2026", font=_font(86), fill="black")
    service = OCRService()
    first = service.run(image, engine="rapidocr")
    second = service.run(image, engine="rapidocr")
    assert first.engine == second.engine == "rapidocr"
    assert first.lines and second.lines, (first, second)
    normalized = first.text.upper().replace(" ", "")
    assert "HELLO" in normalized and "2026" in normalized, first.text
    assert first.width == 920 and first.height == 190
    for line in first.lines:
        assert line.confidence is None or 0 <= line.confidence <= 1
        assert len(line.box) == 4


def test_real_rapidocr_chinese_when_font_available():
    chinese_fonts = (
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    )
    path = next((p for p in chinese_fonts if Path(p).is_file()), None)
    if not path:
        pytest.skip("No CJK font on this runner")
    image = Image.new("RGB", (920, 190), "white")
    ImageDraw.Draw(image).text((32, 28), "本地文字识别测试", font=ImageFont.truetype(path, 80), fill="black")
    result = OCRService().run(image, engine="rapidocr")
    assert result.lines, result
    # Report the raw output; Chinese character-exact-match evaluation will use
    # a fixed, human-reviewed test corpus rather than a runner-dependent font.
    print("Chinese real-model smoke output:", result.text)
