"""Read-only local OCR benchmark over manually reviewed, held-out test crops.

This evaluates recognition only (not text detection or webpage verification).
No predictions are stored, no model training is triggered, and no ground truth
text is returned by the API. All images originate in the local dataset.
"""
from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO

from PIL import Image

from .dataset import DatasetError, DatasetStore
from .engine import OCRService
from .evaluation import edit_distance
from .rec_export import rectify_line

MAX_EVALUATION_REGIONS = 40


def evaluate_reviewed_test(store: DatasetStore, service: OCRService,
                           engine: str = "auto", limit: int = 5,
                           offset: int = 0) -> dict:
    """Measure exact match, CER and inference latency on held-out text crops.

    The selected page is checked *before* inference so large datasets cannot
    unexpectedly start an unbounded OCR job. Crop order is deterministic.
    """
    page = store.reviewed_test_page(limit=limit, offset=offset)
    if not page["items"]:
        raise DatasetError("No reviewed test samples in the selected page")
    count = sum(len(item["annotations"]) for item in page["items"])
    if not 1 <= count <= MAX_EVALUATION_REGIONS:
        raise DatasetError("The selected page must contain 1..40 annotated regions; reduce limit")

    errors = 0
    characters = 0
    exact = 0
    elapsed = 0
    processed = 0
    empty_predictions = 0
    latency_samples: list[int] = []
    length_groups = {
        "1-4": {"regions": 0, "exact_matches": 0, "edit_errors": 0, "reference_characters": 0},
        "5-12": {"regions": 0, "exact_matches": 0, "edit_errors": 0, "reference_characters": 0},
        "13+": {"regions": 0, "exact_matches": 0, "edit_errors": 0, "reference_characters": 0},
    }
    engines: set[str] = set()
    mistakes: list[dict] = []
    for item in page["items"]:
        # Stored content has already passed image format/pixel checks and is
        # always the application's own sanitized PNG, not an arbitrary path.
        with Image.open(BytesIO(store.image(item["id"]))) as stored:
            picture = stored.convert("RGB")
        for region, annotation in enumerate(item["annotations"]):
            crop = rectify_line(picture, annotation["box"])
            result = service.run(crop, engine=engine)
            expected = annotation["text"].strip()
            predicted = result.text.strip()
            distance = edit_distance(expected, predicted)
            errors += distance
            characters += len(expected)
            exact += int(expected == predicted)
            elapsed += result.elapsed_ms
            processed += 1
            empty_predictions += int(not predicted)
            latency_samples.append(max(0, result.elapsed_ms))
            band = "1-4" if len(expected) <= 4 else "5-12" if len(expected) <= 12 else "13+"
            group = length_groups[band]
            group["regions"] += 1
            group["exact_matches"] += int(expected == predicted)
            group["edit_errors"] += distance
            group["reference_characters"] += len(expected)
            engines.add(result.engine)
            if distance and len(mistakes) < 10:
                mistakes.append({
                    "sample_id": item["id"], "region_index": region,
                    "edit_errors": distance, "reference_length": len(expected),
                    "prediction_length": len(predicted),
                })
    if not characters:
        raise DatasetError("Reviewed test labels must not all be empty")
    for group in length_groups.values():
        group["exact_match_rate"] = (round(group["exact_matches"] / group["regions"], 6)
                                     if group["regions"] else None)
        group["cer"] = (round(group["edit_errors"] / group["reference_characters"], 6)
                        if group["reference_characters"] else None)
    latency_samples.sort()
    p50 = latency_samples[(len(latency_samples) - 1) // 2]
    p90 = latency_samples[max(0, (9 * len(latency_samples) + 9) // 10 - 1)]
    return {
        "status": "evaluated_local_engine",
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "split": "test", "reviewed_only": True,
        "requested_engine": engine, "actual_engines": sorted(engines),
        "available_test_samples": page["total"],
        "offset": offset, "next_offset": offset + len(page["items"]),
        "has_more": offset + len(page["items"]) < page["total"],
        "evaluated_samples": len(page["items"]), "evaluated_regions": processed,
        "exact_matches": exact, "exact_match_rate": round(exact / processed, 6),
        "edit_errors": errors, "reference_characters": characters,
        "cer": round(errors / characters, 6),
        "inference_ms_total": elapsed,
        "inference_ms_mean": round(elapsed / processed, 2),
        "quality": {
            "empty_predictions": empty_predictions,
            "latency_ms_p50": p50,
            "latency_ms_p90": p90,
            "by_reference_length": length_groups,
        },
        "error_examples": mistakes,
        "note": "Measured local OCR on manually reviewed held-out test crops only. "
                "No text detection metric, model training, credential handling or remote validation.",
    }
