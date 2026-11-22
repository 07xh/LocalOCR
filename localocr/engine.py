"""Pluggable local OCR backends. No cloud processing or remote URL inputs."""
from __future__ import annotations
import importlib.util
import shutil
import threading
import time
from dataclasses import asdict, dataclass
from typing import Optional
from PIL import Image


class EngineUnavailable(RuntimeError):
    pass


@dataclass
class TextLine:
    text: str
    confidence: Optional[float]
    box: list[list[int]]  # clockwise: top-left, top-right, bottom-right, bottom-left


@dataclass
class OCRResult:
    engine: str
    text: str
    lines: list[TextLine]
    width: int
    height: int
    elapsed_ms: int

    def as_dict(self) -> dict:
        return asdict(self)


def _rect(left: float, top: float, right: float, bottom: float) -> list[list[int]]:
    return [[int(left), int(top)], [int(right), int(top)],
            [int(right), int(bottom)], [int(left), int(bottom)]]


class OCRService:
    def __init__(self):
        self._rapid = None
        self._lock = threading.RLock()

    @staticmethod
    def backends() -> dict[str, bool]:
        return {
            "rapidocr": importlib.util.find_spec("rapidocr") is not None,
            "tesseract": (importlib.util.find_spec("pytesseract") is not None and
                          shutil.which("tesseract") is not None),
        }

    def resolve(self, name: str) -> str:
        if name not in {"auto", "rapidocr", "tesseract"}:
            raise ValueError("Engine must be auto, rapidocr or tesseract")
        available = self.backends()
        if name == "auto":
            name = next((n for n in ("rapidocr", "tesseract") if available[n]), "")
        if not name or not available[name]:
            raise EngineUnavailable("Requested OCR engine is not installed; see README installation steps")
        return name

    def run(self, image: Image.Image, engine: str = "auto") -> OCRResult:
        chosen = self.resolve(engine)
        t0 = time.perf_counter()
        with self._lock:  # keep model initialization and inference bounded
            lines = self._run_rapid(image) if chosen == "rapidocr" else self._run_tesseract(image)
        return OCRResult(engine=chosen, text="\n".join(l.text for l in lines),
                         lines=lines, width=image.width, height=image.height,
                         elapsed_ms=round((time.perf_counter() - t0) * 1000))

    def _run_rapid(self, image: Image.Image) -> list[TextLine]:
        import numpy as np
        if self._rapid is None:
            from rapidocr import RapidOCR
            self._rapid = RapidOCR()
        out = self._rapid(np.asarray(image))
        if not out or out.txts is None:
            return []
        txts = list(out.txts)
        scores = list(out.scores) if out.scores is not None else []
        boxes = list(out.boxes) if out.boxes is not None else []
        lines = []
        for i, text in enumerate(txts):
            text = str(text).strip()
            if not text:
                continue
            score = float(scores[i]) if i < len(scores) else None
            box = [[int(round(float(v))) for v in point] for point in boxes[i]] if i < len(boxes) else _rect(0, 0, image.width, image.height)
            lines.append(TextLine(text=text, confidence=score, box=box))
        return lines

    @staticmethod
    def _run_tesseract(image: Image.Image) -> list[TextLine]:
        import pytesseract
        from pytesseract import Output
        try:
            d = pytesseract.image_to_data(image, output_type=Output.DICT, config="--psm 6")
        except (pytesseract.TesseractError, pytesseract.TesseractNotFoundError) as e:
            raise EngineUnavailable("Tesseract failed: verify installation and language data") from e
        grouped: dict[tuple[int, int, int, int], list[tuple]] = {}
        for i, raw in enumerate(d.get("text", [])):
            value = str(raw).strip()
            if not value:
                continue
            key = tuple(int(d[k][i]) for k in ("page_num", "block_num", "par_num", "line_num"))
            left, top, width, height = [int(d[k][i]) for k in ("left", "top", "width", "height")]
            try:
                confidence = float(d["conf"][i]) / 100
            except (ValueError, TypeError):
                confidence = -1
            grouped.setdefault(key, []).append((value, max(0.0, min(1.0, confidence)), left, top, left + width, top + height))
        lines = []
        for items in grouped.values():
            text = " ".join(v[0] for v in items)
            valid = [v[1] for v in items if v[1] >= 0]
            box = _rect(min(v[2] for v in items), min(v[3] for v in items),
                        max(v[4] for v in items), max(v[5] for v in items))
            lines.append(TextLine(text=text, confidence=round(sum(valid) / len(valid), 4) if valid else None, box=box))
        return lines
