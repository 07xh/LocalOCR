"""Paddle model export must remain opt-in and unverified until compatibility gates pass."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from localocr.models import ModelRegistry
from localocr.model_export import build_paddle_export_plan, export_paddle_checkpoint
from localocr.training import TrainingError


def example_registered(tmp_path):
    root = tmp_path / "training"
    registry = ModelRegistry(root)
    run_id = "b" * 32
    folder = root / "runs" / run_id
    folder.mkdir(parents=True)
    repo = tmp_path / "PaddleOCR"
    (repo / "tools").mkdir(parents=True)
    (repo / "tools" / "export_model.py").write_text("print('fixture')", encoding="utf-8")
    conf = repo / "configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml"
    conf.parent.mkdir(parents=True)
    conf.write_text("Global: {}", encoding="utf-8")
    (folder / "status.json").write_text(json.dumps({
        "id": run_id, "status": "completed",
        "training_config": {"paddle_repo": str(repo)},
    }), encoding="utf-8")
    model = folder / "best_accuracy.pdparams"
    model.write_bytes(b"fixture weights, no actual Paddle model")
    entry = registry.register(run_id, model.name)
    return registry, entry, model


def test_export_plan_uses_registered_provenance_and_fixed_command(tmp_path):
    registry, entry, _ = example_registered(tmp_path)
    plan = build_paddle_export_plan(registry, entry["id"], sys.executable)
    assert plan["cwd"].endswith("PaddleOCR")
    assert plan["args"][0] == str(Path(sys.executable).resolve())
    assert plan["args"][1:5] == [
        "tools/export_model.py", "-c",
        "configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml", "-o"
    ]
    assert any("Global.pretrained_model=" in v for v in plan["args"])
    assert "model_id" in plan and plan["model_id"] == entry["id"]
    assert not any(v.startswith("http") for v in plan["args"])


def test_export_rejects_tampered_weights_and_bad_id(tmp_path):
    registry, entry, model = example_registered(tmp_path)
    model.write_bytes(b"changed")
    with pytest.raises(TrainingError, match="SHA-256"):
        build_paddle_export_plan(registry, entry["id"], sys.executable)
    with pytest.raises(TrainingError, match="Invalid registered"):
        build_paddle_export_plan(registry, "../bad", sys.executable)


def test_export_creates_only_unverified_manifest(tmp_path, monkeypatch):
    registry, entry, _ = example_registered(tmp_path)
    calls = []
    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        output_arg = next(a for a in args if a.startswith("Global.save_inference_dir="))
        directory = Path(json.loads(output_arg.split("=", 1)[1]))
        directory.mkdir(parents=True)
        (directory / "inference.json").write_bytes(b'{"graph":"fixture"}')
        (directory / "inference.pdiparams").write_bytes(b"fixture weights")
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr("localocr.model_export.subprocess.run", fake_run)
    manifest = export_paddle_checkpoint(registry, entry["id"], sys.executable)
    assert manifest["state"] == "paddle_exported_unverified"
    assert "ONNX" in manifest["note"]
    assert not any("activated" in str(c) for c in calls)
    assert calls[0][1]["shell"] is False
    assert calls[0][1]["timeout"] == 1800
    root = registry.root / "exports" / entry["id"]
    assert json.loads((root / "manifest.json").read_text()) == manifest
    assert not (root / "model.onnx").exists()
    with pytest.raises(TrainingError, match="already exists"):
        export_paddle_checkpoint(registry, entry["id"], sys.executable)


def test_failed_export_keeps_logs_without_manifest(tmp_path, monkeypatch):
    registry, entry, _ = example_registered(tmp_path)
    monkeypatch.setattr(
        "localocr.model_export.subprocess.run",
        lambda args, **kwargs: SimpleNamespace(returncode=9),
    )
    with pytest.raises(TrainingError, match="nonzero exit code"):
        export_paddle_checkpoint(registry, entry["id"], sys.executable)
    root = registry.root / "exports" / entry["id"]
    assert (root / "export.log").exists()
    assert not (root / "manifest.json").exists()
