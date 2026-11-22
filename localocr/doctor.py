"""Privacy-preserving local runtime diagnostics.

Never reads user images, never exposes secrets or user filesystem paths, and
does not contact an online model server. Deep mode uses only an original
synthetic text image and must be explicitly requested.
"""
from __future__ import annotations

import importlib.util
from itertools import islice
from pathlib import Path
import sqlite3
import sys
import tempfile

from . import __version__
from .engine import OCRService
from .settings import config_dir


def _bundled_onnx_count() -> int:
    """Count available packaged ONNX files without including absolute paths."""
    roots: list[Path] = []
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        roots.append(Path(sys._MEIPASS))
    else:
        try:
            spec = importlib.util.find_spec("rapidocr")
            if spec and spec.origin:
                roots.append(Path(spec.origin).parent)
        except (ImportError, ValueError):
            pass
    return sum(
        1 for root in roots if root.exists()
        for _ in islice(root.rglob("*.onnx"), 200)
    )


def _local_storage_writable() -> bool:
    try:
        root = config_dir()
        root.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryFile(dir=root) as handle:
            handle.write(b"localocr-doctor")
            handle.flush()
        return True
    except OSError:
        return False


def _sqlite_usable() -> bool:
    try:
        with sqlite3.connect(":memory:") as con:
            return con.execute("SELECT 1").fetchone() == (1,)
    except (OSError, sqlite3.Error):
        return False


def _studio_assets_present() -> bool:
    root = Path(__file__).parent / "web"
    return all((root / file).is_file() for file in
               ("index.html", "studio.js", "studio.css"))


def diagnose(*, deep: bool = False) -> dict:
    """Report only booleans, model count, version and an optional smoke result."""
    backends = OCRService.backends()
    checks = {
        "sqlite_usable": _sqlite_usable(),
        "storage_writable": _local_storage_writable(),
        "studio_assets_present": _studio_assets_present(),
        "ocr_engine_available": any(backends.values()),
    }
    result = {
        "version": __version__,
        "runtime": "portable-exe" if getattr(sys, "frozen", False) else "python",
        "checks": checks,
        "backends": backends,
        "packaged_onnx_count": _bundled_onnx_count(),
        "deep_inference": "not_requested",
    }
    if deep:
        if not backends["rapidocr"]:
            result["deep_inference"] = "unavailable"
        else:
            from PIL import Image, ImageDraw, ImageFont

            font_paths = (
                Path("C:/Windows/Fonts/arial.ttf"),
                Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            )
            font_path = next((p for p in font_paths if p.is_file()), None)
            if font_path is None:
                result["deep_inference"] = "font_unavailable"
            else:
                image = Image.new("RGB", (900, 180), "white")
                font = ImageFont.truetype(str(font_path), 80)
                ImageDraw.Draw(image).text((30, 30), "HELLO 2026",
                                           font=font, fill="black")
                try:
                    output = OCRService().run(image, "rapidocr")
                    normalized = "".join(output.text.upper().split())
                    result["deep_inference"] = (
                        "passed" if "HELLO" in normalized and "2026" in normalized
                        else "failed"
                    )
                except Exception:
                    # Deliberately omit exception strings: they can contain local
                    # paths or environment configuration.
                    result["deep_inference"] = "failed"
    result["ready"] = all(checks.values()) and (
        not deep or result["deep_inference"] == "passed"
    )
    return result
