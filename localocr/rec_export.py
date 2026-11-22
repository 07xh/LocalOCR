"""Export manually reviewed quadrilateral crops for PaddleOCR text recognition.

No training subprocesses, external services, or source uploads are involved here.
"""
from __future__ import annotations

from io import BytesIO
import json
import math
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image

from .dataset import DatasetError, DatasetStore, MAX_EXPORT_BYTES, MAX_IMAGES_FOR_EXPORT

MAX_CROPS = 5000
MAX_CROP_PIXELS = 3_000_000
SPLITS = ("train", "val", "test")


def rectify_line(image: Image.Image, points: list[list[int]]) -> Image.Image:
    """Perspective-correct one clockwise UL,UR,LR,LL quadrilateral.

    Pillow QUAD takes the *source* corners in UL,LL,LR,UR order.
    """
    if len(points) != 4 or any(len(point) != 2 for point in points):
        raise DatasetError("Recognition crop requires four points")
    ul, ur, lr, ll = points

    def distance(a, b):
        return math.hypot(a[0] - b[0], a[1] - b[1])

    width = round(max(distance(ul, ur), distance(ll, lr)))
    height = round(max(distance(ul, ll), distance(ur, lr)))
    if width < 2 or height < 2 or width * height > MAX_CROP_PIXELS:
        raise DatasetError("Recognition crop size is invalid or exceeds 3 megapixels")
    coords = tuple(float(v) for p in (ul, ll, lr, ur) for v in p)
    return image.convert("RGB").transform(
        (width, height), Image.Transform.QUAD, coords,
        resample=Image.Resampling.BICUBIC,
    )


def export_recognition_zip(store: DatasetStore) -> bytes:
    """Produce rec_gt_{train,val,test}.txt with cropped images.

    Each label is an image-relative-path, a literal tab and the
    human-reviewed transcript. No automatic data splits or inferred labels.
    """
    with store._lock:
        with store._connect() as con:
            rows = con.execute(
                "SELECT id,split,annotations FROM samples "
                "WHERE status='reviewed' ORDER BY id"
            ).fetchall()
        if len(rows) > MAX_IMAGES_FOR_EXPORT:
            raise DatasetError(
                f"Export limited to {MAX_IMAGES_FOR_EXPORT} reviewed images"
            )
        out = BytesIO()
        counts = dict.fromkeys(SPLITS, 0)
        total_bytes = 0
        crops = 0
        labels = {split: [] for split in SPLITS}

        with ZipFile(out, "w", ZIP_DEFLATED, compresslevel=3) as archive:
            for row in rows:
                split = row["split"]
                if split == "unassigned":
                    continue
                if split not in SPLITS:
                    raise DatasetError("Unknown split on a reviewed sample")
                annotations = json.loads(row["annotations"])
                try:
                    image = Image.open(store.images / (row["id"] + ".png"))
                    image.load()
                except (OSError, ValueError) as exc:
                    raise DatasetError("A reviewed sample image could not be read") from exc
                for i, line in enumerate(annotations):
                    transcription = line["text"]
                    # PaddleOCR SimpleDataSet splits labels at a tab/newline.
                    if not transcription or any(c in transcription for c in "\r\n\t"):
                        raise DatasetError("Recognition labels cannot contain tabs/newlines")
                    crops += 1
                    if crops > MAX_CROPS:
                        raise DatasetError("Recognition export exceeds 5000 text crops")
                    crop = rectify_line(image, line["box"])
                    buffer = BytesIO()
                    crop.save(buffer, "PNG")
                    data = buffer.getvalue()
                    total_bytes += len(data)
                    if total_bytes > MAX_EXPORT_BYTES:
                        raise DatasetError("Export exceeds 128 MiB of cropped images")
                    name = f"rec/{split}/{row['id']}_{i:04d}.png"
                    archive.writestr(name, data)
                    labels[split].append(f"{name}\t{transcription}\n")
                    counts[split] += 1

            for split in SPLITS:
                archive.writestr(f"rec_gt_{split}.txt", "".join(labels[split]))
            archive.writestr("manifest.json", json.dumps({
                "format": "PaddleOCR text recognition SimpleDataSet",
                "reviewed_only": True,
                "split_counts": counts,
                "crop_count": crops,
                "labels": {s: f"rec_gt_{s}.txt" for s in SPLITS},
                "data_dir": ".",
                "note": "Only reviewed and explicitly assigned samples. "
                        "Separate test split is never used as training data.",
            }, ensure_ascii=False, indent=2))
        return out.getvalue()
