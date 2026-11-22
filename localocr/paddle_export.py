"""Export manually reviewed OCR annotations in PPOCRLabel/PaddleOCR detection format.

This is a data exporter only. It does not train a model or perform online actions.
"""
from __future__ import annotations

from io import BytesIO
import json
from zipfile import ZIP_DEFLATED, ZipFile

from .dataset import (
    DatasetError, DatasetStore, MAX_EXPORT_BYTES, MAX_IMAGES_FOR_EXPORT,
)


def export_detection_zip(store: DatasetStore) -> bytes:
    """Return a ZIP containing Label.txt and det/{train,val,test}.txt.

    Only *human-reviewed* annotations are exported. Images with the
    'unassigned' split remain editable in Label.txt but are excluded
    from train/validation/test manifests; no split is silently inferred.
    Paths are relative to the ZIP extraction root, ready for PaddleOCR
    detection datasets (data_dir = extraction root).
    """
    with store._lock:
        with store._connect() as con:
            rows = con.execute(
                "SELECT id, split, annotations FROM samples "
                "WHERE status='reviewed' ORDER BY id"
            ).fetchall()

        if len(rows) > MAX_IMAGES_FOR_EXPORT:
            raise DatasetError(
                f"Export limited to {MAX_IMAGES_FOR_EXPORT} reviewed images"
            )

        images = []
        total_bytes = 0
        counts = {k: 0 for k in ("train", "val", "test", "unassigned")}
        for row in rows:
            # Only UUID-generated file names, never user-supplied paths.
            path = store.images / (row["id"] + ".png")
            try:
                blob = path.read_bytes()
            except FileNotFoundError as exc:
                raise DatasetError("A reviewed sample image is missing") from exc
            total_bytes += len(blob)
            if total_bytes > MAX_EXPORT_BYTES:
                raise DatasetError("Export exceeds 128 MiB")
            labels = json.loads(row["annotations"])
            if not labels:
                raise DatasetError("A reviewed sample has no annotations")
            if row["split"] not in counts:
                raise DatasetError("Unknown dataset split")
            annotation = [
                {"transcription": line["text"], "points": line["box"],
                 "difficult": False}
                for line in labels
            ]
            image_name = "images/" + row["id"] + ".png"
            label_line = image_name + "\t" + json.dumps(
                annotation, ensure_ascii=False, separators=(",", ":")
            ) + "\n"
            images.append((image_name, blob, row["split"], label_line))
            counts[row["split"]] += 1

        with ZipFile(out := BytesIO(), "w", ZIP_DEFLATED, compresslevel=3) as archive:
            for image_name, blob, _, _ in images:
                archive.writestr(image_name, blob)
            archive.writestr("Label.txt", "".join(x[3] for x in images))
            for split in ("train", "val", "test"):
                archive.writestr(
                    "det/" + split + ".txt",
                    "".join(x[3] for x in images if x[2] == split),
                )
            archive.writestr("manifest.json", json.dumps({
                "format": "PPOCRLabel / PaddleOCR text detection",
                "reviewed_only": True,
                "count": len(images),
                "split_counts": counts,
                "label_file": "Label.txt",
                "training_labels": ["det/train.txt", "det/val.txt", "det/test.txt"],
                "note": "Detection labels only. No recognition crops or model training.",
            }, ensure_ascii=False, indent=2))
        return out.getvalue()
