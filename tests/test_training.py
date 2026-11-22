"""Local training plan and subprocess orchestration without actually training."""
from __future__ import annotations

from pathlib import Path
import json

import pytest

from localocr.training import TrainingManager, TrainingError, build_plan


def fixture_layout(tmp_path):
    repo = tmp_path / "PaddleOCR"
    config = repo / "configs" / "rec" / "PP-OCRv5" / "PP-OCRv5_mobile_rec.yml"
    config.parent.mkdir(parents=True)
    config.write_text("Global:\n  use_gpu: true\n", encoding="utf-8")
    (repo / "tools").mkdir()
    (repo / "tools" / "train.py").write_text("# fixture - not executed", encoding="utf-8")
    data = tmp_path / "reviewed-rec"
    (data / "rec" / "train").mkdir(parents=True)
    (data / "rec" / "val").mkdir(parents=True)
    (data / "rec" / "test").mkdir(parents=True)
    for split, count in (("train", 3), ("val", 1), ("test", 1)):
        lines = []
        for i in range(count):
            name = f"rec/{split}/{i}.png"
            (data / name).write_bytes(b"fixture png")
            lines.append(f"{name}\t真实标签 {i}\n")
        (data / f"rec_gt_{split}.txt").write_text("".join(lines), encoding="utf-8")
    weights = tmp_path / "trusted-pretrained.pdparams"
    weights.write_bytes(b"mock weights")
    return repo, data, weights


def test_build_plan_uses_only_local_train_val_and_fixed_script(tmp_path):
    repo, data, weights = fixture_layout(tmp_path)
    plan = build_plan(str(repo), str(data), str(weights), epochs=3,
                      batch_size=2, output_dir=tmp_path / "out")
    assert plan["train_count"] == 3
    assert plan["val_count"] == 1
    assert plan["test_count"] == 1
    assert plan["args"][1:4] == ["tools/train.py", "-c", "configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml"]
    joined = "\n".join(plan["args"])
    assert "Global.epoch_num=3" in joined
    assert "Global.distributed=false" in joined
    assert "Train.loader.batch_size_per_card=2" in joined
    assert "rec_gt_train.txt" in joined and "rec_gt_val.txt" in joined
    assert "rec_gt_test.txt" not in joined
    assert all(not x.startswith("http") for x in plan["args"])


def test_training_rejects_missing_weights_small_and_unsafe_dataset(tmp_path):
    repo, data, weights = fixture_layout(tmp_path)
    with pytest.raises(TrainingError, match="pretrained"):
        build_plan(str(repo), str(data), str(tmp_path / "missing.pdparams"))
    with pytest.raises(TrainingError, match="batch size"):
        build_plan(str(repo), str(data), str(weights), batch_size=4)
    with pytest.raises(TrainingError, match="epochs"):
        build_plan(str(repo), str(data), str(weights), epochs=0)
    (data / "rec_gt_train.txt").write_text("../secret.png\tbad\n", encoding="utf-8")
    with pytest.raises(TrainingError, match="unsafe"):
        build_plan(str(repo), str(data), str(weights))


class FakeProcess:
    def __init__(self):
        self.pid = 1337
        self.code = None

    def poll(self):
        return self.code

    def terminate(self):
        self.code = -15


def test_training_manager_subprocess_start_status_and_finish(tmp_path, monkeypatch):
    repo, data, weights = fixture_layout(tmp_path)
    plan = build_plan(str(repo), str(data), str(weights),
                      batch_size=2, output_dir=tmp_path / "train-output")
    process = FakeProcess()
    captured = {}

    def fake_popen(args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return process

    monkeypatch.setattr("localocr.training.subprocess.Popen", fake_popen)
    manager = TrainingManager(tmp_path / "jobs")
    status = manager.start(plan)
    assert status["status"] == "running"
    assert json.loads((Path(status["output_dir"]) / "status.json").read_text())["status"] == "running"
    assert captured["kwargs"]["shell"] is False
    assert captured["kwargs"]["stdin"] is not None
    assert Path(status["output_dir"]).is_dir()
    with pytest.raises(TrainingError, match="already running"):
        manager.start(plan)
    (Path(status["output_dir"]) / "train.log").write_text("epoch: [2/10], global_step: 2\n", encoding="utf-8")
    live = manager.status()
    assert live["epoch_current"] == 2 and live["epoch_percent"] == 20.0
    (Path(status["output_dir"]) / "best_accuracy.pdparams").write_bytes(b"model fixture")
    process.code = 0
    finished = manager.status()
    assert finished["status"] == "completed"
    assert finished["exit_code"] == 0
    assert finished["model_files"] == ["best_accuracy.pdparams"]
    assert "epoch: [2/10]" in finished["log_tail"]
    assert json.loads((Path(status["output_dir"]) / "status.json").read_text())["status"] == "completed"


def test_cancel_running_training_and_terminal_status(tmp_path, monkeypatch):
    repo, data, weights = fixture_layout(tmp_path)
    plan = build_plan(str(repo), str(data), str(weights),
                      batch_size=2, output_dir=tmp_path / "train-out")
    process = FakeProcess()
    monkeypatch.setattr("localocr.training.subprocess.Popen", lambda *a, **k: process)
    monkeypatch.setattr("localocr.training.os.killpg", lambda pid, signum: process.terminate())
    manager = TrainingManager(tmp_path / "jobs")
    manager.start(plan)
    result = manager.cancel()
    assert result["status"] == "cancelled"
    with pytest.raises(TrainingError, match="No active"):
        manager.cancel()


def test_training_plan_api_needs_auth_and_returns_readiness(tmp_path):
    from fastapi.testclient import TestClient
    from localocr.api import create_app

    repo, data, weights = fixture_layout(tmp_path)
    client = TestClient(create_app(token="example-training-key"))
    payload = {"paddle_repo": str(repo), "dataset_dir": str(data),
               "pretrained_model": str(weights), "epochs": 2, "batch_size": 2}
    assert client.post("/v1/training/plan", json=payload).status_code == 401
    response = client.post("/v1/training/plan", json=payload,
                           headers={"X-API-Key": "example-training-key"})
    assert response.status_code == 200, response.text
    assert response.json()["train_count"] == 3
    assert client.post("/v1/training/start", json={**payload, "epochs": 0},
                       headers={"X-API-Key": "example-training-key"}).status_code == 422
