"""Regression checks for reliable local storage and model errors."""
from __future__ import annotations

import json
import sqlite3
from types import SimpleNamespace

from PIL import Image
import pytest
from fastapi.testclient import TestClient

from localocr.api import create_app
from localocr.dataset import DatasetStore
from localocr.engine import OCRService, EngineUnavailable
from localocr.models import ModelRegistry
from localocr.training import TrainingError


def test_failed_sample_insert_does_not_leave_untracked_png(tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    with store._connect() as con:
        con.execute(
            "CREATE TRIGGER deny_insert BEFORE INSERT ON samples "
            "BEGIN SELECT RAISE(ABORT, 'blocked'); END"
        )
    with pytest.raises(sqlite3.IntegrityError):
        store.add(Image.new("RGB", (60, 35), "white"))
    assert list(store.images.glob("*.png")) == []
    assert store.stats()["total"] == 0


def test_uuid_collision_never_overwrites_existing_image(tmp_path, monkeypatch):
    store = DatasetStore(tmp_path / "dataset")
    first = store.add(Image.new("RGB", (60, 35), "white"))
    raw_before = store.image(first["id"])
    monkeypatch.setattr("localocr.dataset.uuid4",
                        lambda: SimpleNamespace(hex=first["id"]))
    with pytest.raises(FileExistsError):
        store.add(Image.new("RGB", (60, 35), "black"))
    assert store.image(first["id"]) == raw_before
    assert store.stats()["total"] == 1


def test_model_registry_corruption_is_contained(tmp_path):
    root = tmp_path / "training"
    registry = ModelRegistry(root)
    registry.index.write_text("{invalid", encoding="utf-8")
    with pytest.raises(TrainingError, match="invalid JSON"):
        registry.list()


def test_corrupt_model_registry_returns_controlled_api_error(tmp_path, monkeypatch):
    root = tmp_path / "training"
    registry = ModelRegistry(root)
    registry.index.write_text("{invalid", encoding="utf-8")
    monkeypatch.setattr("localocr.api.ModelRegistry", lambda: registry)
    client = TestClient(create_app(token="fixture-key"))
    response = client.get("/v1/models", headers={"X-API-Key": "fixture-key"})
    assert response.status_code == 400
    assert "invalid JSON" in response.json()["detail"]


def test_unexpected_tesseract_exception_is_engine_unavailable(monkeypatch):
    service = OCRService()
    monkeypatch.setattr(service, "resolve", lambda name: "tesseract")
    def fail(_image):
        raise RuntimeError("bad local runtime")
    monkeypatch.setattr(service, "_run_tesseract", fail)
    with pytest.raises(EngineUnavailable, match="Tesseract"):
        service.run(Image.new("RGB", (60, 35), "white"), "tesseract")
