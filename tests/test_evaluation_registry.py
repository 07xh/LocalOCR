"""Held-out CER / exact-match evaluation, checkpoint registry and API tests."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from localocr.api import create_app
from localocr.evaluation import edit_distance, evaluate_recognition
from localocr.models import ModelRegistry
from localocr.training import TrainingError, TrainingManager


def dataset(tmp_path: Path):
    root = tmp_path / "rec-data"
    (root / "rec" / "test").mkdir(parents=True)
    (root / "rec" / "train").mkdir(parents=True)
    entries = [
        ("rec/test/a.png", "你好A"),
        ("rec/test/b.png", "abc"),
    ]
    for name, _ in entries:
        (root / name).write_bytes(b"png fixture")
    (root / "rec_gt_test.txt").write_text(
        "".join(f"{name}\t{text}\n" for name, text in entries), encoding="utf-8"
    )
    return root, entries


def predict(tmp_path: Path, rows: list[dict]):
    path = tmp_path / "predictions.jsonl"
    path.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
                    encoding="utf-8")
    return path


def test_character_error_rate_and_exact_match_on_test_set(tmp_path):
    root, entries = dataset(tmp_path)
    path = predict(tmp_path, [
        {"image": entries[0][0], "text": "你好B"},
        {"image": entries[1][0], "text": "abc"},
    ])
    report = evaluate_recognition(str(root), str(path))
    assert edit_distance("你好A", "你好B") == 1
    assert edit_distance("", "你好") == 2
    assert report["test_samples"] == 2
    assert report["predicted_samples"] == 2
    assert report["missing_predictions"] == 0
    assert report["exact_matches"] == 1
    assert report["exact_match_rate"] == 0.5
    assert report["edit_errors"] == 1
    assert report["reference_characters"] == 6
    assert report["cer"] == round(1 / 6, 6)
    assert report["label_sha256"] == sha256((root / "rec_gt_test.txt").read_bytes()).hexdigest()
    assert "你好A" not in str(report)  # no reference labels in returned error details


def test_missing_predictions_penalized_and_extra_rejected(tmp_path):
    root, entries = dataset(tmp_path)
    path = predict(tmp_path, [{"image": entries[0][0], "text": "你好A"}])
    metrics = evaluate_recognition(str(root), str(path))
    assert metrics["missing_predictions"] == 1
    assert metrics["exact_matches"] == 1
    assert metrics["cer"] == 0.5
    path = predict(tmp_path, [{"image": "rec/train/x.png", "text": "not held-out"}])
    with pytest.raises(TrainingError, match="held-out"):
        evaluate_recognition(str(root), str(path))


def test_duplicate_prediction_and_zero_test_rejected(tmp_path):
    root, entries = dataset(tmp_path)
    item = {"image": entries[0][0], "text": "x"}
    path = predict(tmp_path, [item, item])
    with pytest.raises(TrainingError, match="Duplicate"):
        evaluate_recognition(str(root), str(path))
    (root / "rec_gt_test.txt").write_text("", encoding="utf-8")
    with pytest.raises(TrainingError, match="No held-out"):
        evaluate_recognition(str(root), str(path))


def run_folder(root: Path, *, status: str = "completed"):
    run_id = "a" * 32
    folder = root / "runs" / run_id
    folder.mkdir(parents=True)
    metadata = {
        "id": run_id, "output_dir": str(folder), "status": status,
        "started_at": "2026-11-22T00:00:00+00:00", "exit_code": 0,
    }
    (folder / "status.json").write_text(json.dumps(metadata), encoding="utf-8")
    (folder / "best_accuracy.pdparams").write_bytes(b"fixture only - model is not verified")
    return run_id, folder


def test_checkpoint_registry_only_completed_and_idempotent(tmp_path):
    root = tmp_path / "training"
    run_id, folder = run_folder(root)
    registry = ModelRegistry(root)
    first = registry.register(run_id, "best_accuracy.pdparams")
    assert first["state"] == "registered_unverified"
    assert first["sha256"] == sha256((folder / "best_accuracy.pdparams").read_bytes()).hexdigest()
    assert registry.register(run_id, "best_accuracy.pdparams")["id"] == first["id"]
    assert ModelRegistry(root).list() == [first]
    with pytest.raises(TrainingError, match="valid training run"):
        registry.register("../" + run_id, "best_accuracy.pdparams")
    with pytest.raises(TrainingError, match="filename"):
        registry.register(run_id, "../bad.pdparams")
    (folder / "status.json").write_text(json.dumps({"id": run_id, "status": "running"}),
                                        encoding="utf-8")
    with pytest.raises(TrainingError, match="completed"):
        registry.register(run_id, "best_accuracy.pdparams")


def test_persisted_run_history_marks_orphaned_running_unknown(tmp_path):
    root = tmp_path / "training"
    run_id, folder = run_folder(root, status="running")
    history = TrainingManager(root).history()
    assert len(history) == 1
    assert history[0]["status"] == "unknown_after_restart"
    assert history[0]["id"] == run_id
    assert json.loads((folder / "status.json").read_text())["status"] == "running"


def test_evaluation_and_models_require_key(tmp_path, monkeypatch):
    root, entries = dataset(tmp_path)
    path = predict(tmp_path, [{"image": entries[0][0], "text": entries[0][1]},
                              {"image": entries[1][0], "text": entries[1][1]}])
    training_root = tmp_path / "training"
    run_id, _ = run_folder(training_root)
    monkeypatch.setattr("localocr.api.ModelRegistry", lambda: ModelRegistry(training_root))
    client = TestClient(create_app(token="fixture-key"))
    assert client.get("/v1/models").status_code == 401
    assert client.post("/v1/evaluation/recognition", json={
        "dataset_dir": str(root), "predictions_path": str(path)
    }).status_code == 401
    headers = {"X-API-Key": "fixture-key"}
    assert client.post("/v1/evaluation/recognition", json={
        "dataset_dir": str(root), "predictions_path": str(path)
    }, headers=headers).json()["exact_match_rate"] == 1.0
    entry = client.post("/v1/models/register", json={
        "run_id": run_id, "filename": "best_accuracy.pdparams"
    }, headers=headers)
    assert entry.status_code == 200, entry.text
    items = client.get("/v1/models", headers=headers).json()["items"]
    assert len(items) == 1 and items[0]["id"] == entry.json()["id"]
    assert client.get("/v1/training/history", headers=headers).status_code == 200
