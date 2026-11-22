"""Offline recognition benchmark against an explicit, held-out PaddleOCR test split.

Predictions must be produced separately by an explicitly chosen model and stored
as JSONL rows {"image": "rec/test/....png", "text": "recognized"}.
No automatic model inference, cloud connections or hidden data collection.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from .training import TrainingError, _verified_labels

MAX_EVAL_FILE_BYTES = 5 * 1024 * 1024
MAX_EVAL_ROWS = 5000


def edit_distance(a: str, b: str) -> int:
    """Unicode codepoint Levenshtein distance in O(min(m,n)) memory."""
    if len(a) < len(b):
        a, b = b, a
    previous = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        current = [i]
        for j, y in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (x != y)))
        previous = current
    return previous[-1]


def _bounded_lines(path: Path) -> list[str]:
    if not path.is_file() or path.stat().st_size > MAX_EVAL_FILE_BYTES:
        raise TrainingError("Evaluation file is missing or exceeds 5 MiB")
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    if len(lines) > MAX_EVAL_ROWS:
        raise TrainingError("Evaluation is limited to 5000 rows")
    return lines


def evaluate_recognition(dataset_dir: str, predictions_path: str) -> dict:
    """Score a reviewed, explicitly assigned test split without leaking its labels.

    Missing predictions are counted as fully incorrect. Extra predictions are
    rejected to catch accidental train/validation split evaluations.
    """
    root = Path(dataset_dir).expanduser().resolve()
    prediction_file = Path(predictions_path).expanduser().resolve()
    test_path = root / "rec_gt_test.txt"
    expected_count = _verified_labels(root, "rec_gt_test.txt")
    if not expected_count:
        raise TrainingError("No held-out test examples; assign and review test samples")
    gt = {}
    for line in _bounded_lines(test_path):
        if not line:
            continue
        relative, text = line.split("\t", 1)
        if relative in gt:
            raise TrainingError("Duplicate image in held-out labels")
        gt[relative] = text
    predictions = {}
    for line in _bounded_lines(prediction_file):
        if not line:
            continue
        try:
            record = json.loads(line)
        except (json.JSONDecodeError, TypeError) as exc:
            raise TrainingError("Predictions must be UTF-8 JSONL") from exc
        if not isinstance(record, dict) or set(record) != {"image", "text"}:
            raise TrainingError('Each prediction needs exactly "image" and "text"')
        name, text = record["image"], record["text"]
        if not isinstance(name, str) or not isinstance(text, str):
            raise TrainingError("Prediction path/text must be strings")
        if name in predictions:
            raise TrainingError("Duplicate prediction for one image")
        if name not in gt:
            raise TrainingError("Prediction image is not in the held-out test split")
        predictions[name] = text

    errors = 0
    characters = 0
    exact = 0
    preview = []
    for image_path, expected in gt.items():
        predicted = predictions.get(image_path, "")
        dist = edit_distance(expected, predicted)
        errors += dist
        characters += len(expected)
        exact += int(image_path in predictions and expected == predicted)
        if dist and len(preview) < 10:
            preview.append({"image": image_path, "edits": dist,
                            "reference_length": len(expected),
                            "prediction_length": len(predicted)})
    if not characters:
        raise TrainingError("Test labels cannot all be empty")
    # File hashes make reports independently reproducible without including
    # sensitive reference text inside API responses.
    return {
        "status": "evaluated_offline",
        "evaluated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "split": "test", "test_samples": len(gt), "predicted_samples": len(predictions),
        "missing_predictions": len(gt) - len(predictions),
        "exact_matches": exact, "exact_match_rate": round(exact / len(gt), 6),
        "edit_errors": errors, "reference_characters": characters,
        "cer": round(errors / characters, 6),
        "label_sha256": sha256(test_path.read_bytes()).hexdigest(),
        "prediction_sha256": sha256(prediction_file.read_bytes()).hexdigest(),
        "error_examples": preview,
        "note": "Metrics compare user-supplied predictions on reserved test labels; "
                "no model inference or fine-tuning is performed by this endpoint.",
    }
