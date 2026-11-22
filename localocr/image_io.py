"""Bounded, safe decoding of user-provided images."""
from __future__ import annotations
import base64
import binascii
from io import BytesIO
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 8 * 1024 * 1024
MAX_PIXELS = 12_000_000
ALLOWED = {"PNG", "JPEG", "WEBP", "BMP", "TIFF"}
Image.MAX_IMAGE_PIXELS = MAX_PIXELS

class InvalidImage(ValueError):
    pass


def load_image(data: bytes) -> Image.Image:
    if not data or len(data) > MAX_BYTES:
        raise InvalidImage("Image must be between 1 byte and 8 MiB")
    try:
        with Image.open(BytesIO(data)) as probe:
            if probe.format not in ALLOWED:
                raise InvalidImage("Unsupported image format; use PNG/JPEG/WEBP/BMP/TIFF")
            w, h = probe.size
            if w <= 0 or h <= 0 or w * h > MAX_PIXELS:
                raise InvalidImage("Image exceeds 12 megapixels")
            probe.verify()
        with Image.open(BytesIO(data)) as src:
            src.load()
            image = ImageOps.exif_transpose(src).convert("RGB")
            return image.copy()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        if isinstance(e, InvalidImage):
            raise
        raise InvalidImage("Invalid or corrupted image") from e


def decode_base64(value: str) -> Image.Image:
    if not isinstance(value, str):
        raise InvalidImage("image_base64 must be a string")
    if value.startswith("data:"):
        if ";base64," not in value:
            raise InvalidImage("Expected a base64 data URI")
        value = value.split(";base64,", 1)[1]
    if len(value) > ((MAX_BYTES + 2) // 3) * 4 + 32:
        raise InvalidImage("Encoded image exceeds 8 MiB")
    try:
        raw = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as e:
        raise InvalidImage("Malformed base64 image") from e
    return load_image(raw)
