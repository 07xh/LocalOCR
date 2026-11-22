"""Tests for safe PaddleOCR checkpoint resumption and CLI override semantics."""
from __future__ import annotations

import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from localocr.api import create_app
from localocr.dataset import DatasetStore
from localocr.training import TrainingError, build_plan

RUN_ID = "b" * 32


def make_fixture(tmp_path):
    repo = tmp_path / "PaddleOCR"
    config = repo / "configs" / "rec" / "PP-OCRv5" / "PP-OCRv5_mobile_rec.yml"
    config.parent.mkdir(parents=True)
    config.write_text("Global:\n  checkpoints:\n", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "train.py").write_text("# only a local test fixture", encoding="utf-8")
    data = tmp_path / "dataset"
    for split, count in (("train", 3), ("val", 1), ("test", 1)):
        folder = data / "rec" / split
        folder.mkdir(parents=True)
        content = ""
        for i in range(count):
            name = f"rec/{split}/sample{i}.png"
            (data / name).write_bytes(b"local-only-image")
            content += f"{name}\tOCR example {i}\n"
        (data / f"rec_gt_{split}.txt").write_text(content, encoding="utf-8")
    weight = tmp_path / "pretrained.pdparams"
    weight.write_bytes(b"local model placeholder")
    return repo, data, weight


def previous_run(repo, data, weight, root, *, status="cancelled", epochs=10,
                 checkpoint="latest", config=None):
    base = build_plan(str(repo), str(data), str(weight), batch_size=2)
    folder = root / RUN_ID
    folder.mkdir(parents=True)
    (folder / "status.json").write_text(json.dumps({
        "id": RUN_ID,
        "status": status,
        "epochs": epochs,
        "training_config": config if config is not None else base["training_config"],
    }), encoding="utf-8")
    for extension in (".pdparams", ".pdopt", ".states"):
        (folder / (checkpoint + extension)).write_bytes(b"checkpoint fixture")
    return folder


def resume(repo, data, weight, root, **kwargs):
    return build_plan(
        str(repo), str(data), str(weight),
        epochs=kwargs.pop("epochs", 20), batch_size=kwargs.pop("batch_size", 2),
        resume_run_id=kwargs.pop("resume_run_id", RUN_ID),
        resume_checkpoint=kwargs.pop("resume_checkpoint", "latest"),
        resume_root=root, **kwargs,
    )


def test_resume_uses_checkpoints_and_preserves_optimizer_and_test_split(tmp_path):
    repo, data, weight = make_fixture(tmp_path)
    root = tmp_path / "runs"
    folder = previous_run(repo, data, weight, root, status="cancelled")
    plan = resume(repo, data, weight, root, output_dir=tmp_path / "new-run")
    expected = str(folder / "latest")
    assert "Global.checkpoints=" + json.dumps(expected) in plan["args"]
    assert 'Global.pretrained_model=""' in plan["args"]
    assert "rec_gt_test.txt" not in " ".join(plan["args"])
    assert plan["resume_from"] == {"run_id": RUN_ID, "checkpoint": "latest"}
    assert plan["training_config"]["train_labels_sha256"] != ""


def test_resume_best_accuracy_and_completed_epoch_guard(tmp_path):
    repo, data, weight = make_fixture(tmp_path)
    root = tmp_path / "runs"
    previous_run(repo, data, weight, root, status="completed",
                 checkpoint="best_accuracy", epochs=10)
    with pytest.raises(TrainingError, match="greater target epoch"):
        resume(repo, data, weight, root, epochs=10,
               resume_checkpoint="best_accuracy")
    plan = resume(repo, data, weight, root, epochs=16,
                  resume_checkpoint="best_accuracy")
    assert str(root / RUN_ID / "best_accuracy") in " ".join(plan["args"])
    assert plan["resume_from"]["checkpoint"] == "best_accuracy"


def test_resume_requires_complete_checkpoint_and_inactive_status(tmp_path):
    repo, data, weight = make_fixture(tmp_path)
    root = tmp_path / "runs"
    folder = previous_run(repo, data, weight, root, status="running")
    with pytest.raises(TrainingError, match="active or unverified"):
        resume(repo, data, weight, root)
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    status["status"] = "failed"
    (folder / "status.json").write_text(json.dumps(status), encoding="utf-8")
    (folder / "latest.pdopt").unlink()
    with pytest.raises(TrainingError, match="pdopt"):
        resume(repo, data, weight, root)
    with pytest.raises(TrainingError, match="run ID"):
        resume(repo, data, weight, root, resume_run_id="../")


def test_resume_rejects_changed_training_labels_and_model_options(tmp_path):
    repo, data, weight = make_fixture(tmp_path)
    root = tmp_path / "runs"
    previous_run(repo, data, weight, root)
    with pytest.raises(TrainingError, match="configuration"):
        resume(repo, data, weight, root, batch_size=1)
    labels = data / "rec_gt_train.txt"
    labels.write_text(labels.read_text(encoding="utf-8").replace("example", "changed"),
                      encoding="utf-8")
    with pytest.raises(TrainingError, match="configuration"):
        resume(repo, data, weight, root)


def test_resume_rejects_unrecorded_legacy_task(tmp_path):
    repo, data, weight = make_fixture(tmp_path)
    root = tmp_path / "runs"
    folder = previous_run(repo, data, weight, root)
    status = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    status.pop("training_config")
    (folder / "status.json").write_text(json.dumps(status), encoding="utf-8")
    with pytest.raises(TrainingError, match="configuration"):
        resume(repo, data, weight, root)


def test_resume_api_auth_and_parameter_validation(tmp_path, monkeypatch):
    repo, data, weight = make_fixture(tmp_path)
    # API build_plan uses the application training directory, rather than
    # allowing the client to supply an arbitrary resume_root.
    monkeypatch.setattr("localocr.training.config_dir", lambda: tmp_path)
    root = tmp_path / "training" / "runs"
    previous_run(repo, data, weight, root)
    client = TestClient(create_app(token="test-resume-only",
                                   store=DatasetStore(tmp_path / "annotations")))
    payload = {
        "paddle_repo": str(repo), "dataset_dir": str(data),
        "pretrained_model": str(weight), "batch_size": 2,
        "epochs": 15, "resume_run_id": RUN_ID, "resume_checkpoint": "latest",
    }
    assert client.post("/v1/training/plan", json=payload).status_code == 401
    ok = client.post("/v1/training/plan", json=payload,
                     headers={"X-API-Key": "test-resume-only"})
    assert ok.status_code == 200, ok.text
    assert ok.json()["resume_from"]["run_id"] == RUN_ID
    bad = client.post("/v1/training/plan",
                      json={**payload, "resume_run_id": "../../other"},
                      headers={"X-API-Key": "test-resume-only"})
    assert bad.status_code == 422


def test_history_exposes_only_complete_resume_candidates(tmp_path):
    from localocr.training import TrainingManager
    repo, data, weight = make_fixture(tmp_path)
    root = tmp_path / "training" / "runs"
    folder = previous_run(repo, data, weight, root, status="failed")
    manager = TrainingManager(tmp_path / "training")
    history = manager.history()
    assert len(history) == 1
    assert history[0]["resume_candidates"] == ["latest"]
    (folder / "latest.states").unlink()
    assert manager.history()[0]["resume_candidates"] == []
