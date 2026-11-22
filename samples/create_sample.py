"""Create a local test image (no website, account or CAPTCHA integration)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

out = Path(__file__).resolve().parent / 'sample.png'
image = Image.new('RGB', (720, 155), 'white')
draw = ImageDraw.Draw(image)
font = None
for path in ('C:/Windows/Fonts/arial.ttf', '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'):
    if Path(path).exists():
        font = ImageFont.truetype(path, 48)
        break
draw.text((32, 38), 'LocalOCR 2026', fill='black', font=font)
image.save(out)
print(out)
