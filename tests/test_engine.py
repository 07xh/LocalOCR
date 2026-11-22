import shutil
from pathlib import Path
import pytest
from PIL import Image, ImageDraw, ImageFont
from localocr.engine import OCRService
from localocr.image_io import InvalidImage, load_image


def test_bad_format():
    with pytest.raises(InvalidImage):
        load_image(b'not an image')


def test_real_tesseract_ocr():
    pytest.importorskip('pytesseract')
    if not shutil.which('tesseract'):
        pytest.skip('Tesseract executable missing')
    image = Image.new('RGB', (730, 140), 'white')
    draw = ImageDraw.Draw(image)
    paths = ['/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf', 'C:/Windows/Fonts/arial.ttf']
    fontfile = next((p for p in paths if Path(p).exists()), None)
    if fontfile is None:
        pytest.skip('No test font')
    draw.text((20, 25), 'LOCAL OCR 2026', fill='black', font=ImageFont.truetype(fontfile, 50))
    result = OCRService().run(image, 'tesseract')
    assert 'LOCAL' in result.text.upper(), result.text
    assert '2026' in result.text
    assert len(result.lines) >= 1
    assert len(result.lines[0].box) == 4
    assert result.engine == 'tesseract'


def test_rapidocr_result_conversion_without_models():
    import numpy as np
    class FakeOutput:
        txts = ('Example OCR',)
        scores = (0.96,)
        boxes = np.array([[[3, 4], [103, 4], [103, 24], [3, 24]]])
    service = OCRService()
    service._rapid = lambda image: FakeOutput()
    out = service._run_rapid(Image.new('RGB', (300, 100), 'white'))
    assert out[0].text == 'Example OCR'
    assert out[0].confidence == 0.96
    assert out[0].box == [[3, 4], [103, 4], [103, 24], [3, 24]]
