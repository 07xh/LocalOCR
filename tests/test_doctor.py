"""Privacy and status regression tests for local self diagnostics."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from localocr.api import create_app
from localocr.doctor import diagnose


def test_doctor_quick_does_not_disclose_local_secret_or_paths(tmp_path, monkeypatch):
    import localocr.doctor as doctor

    monkeypatch.setattr(doctor, "config_dir", lambda: tmp_path / "secret-parent")
    monkeypatch.setattr(doctor, "_bundled_onnx_count", lambda: 3)
    result = diagnose()
    assert result["checks"]["sqlite_usable"] is True
    assert result["checks"]["storage_writable"] is True
    assert result["checks"]["studio_assets_present"] is True
    assert result["packaged_onnx_count"] == 3
    assert result["deep_inference"] == "not_requested"
    serialized = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "api_key" not in serialized.lower()
    assert "password" not in serialized.lower()


def test_diagnostics_api_requires_auth(tmp_path, monkeypatch):
    import localocr.doctor as doctor

    monkeypatch.setattr(doctor, "config_dir", lambda: tmp_path / "local-only")
    client = TestClient(create_app(token="local-only-test-key"))
    assert client.get("/v1/diagnostics").status_code == 401
    res = client.get("/v1/diagnostics", headers={"X-API-Key": "local-only-test-key"})
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["checks"]["sqlite_usable"] is True
    assert data["checks"]["studio_assets_present"] is True
    assert data["runtime"] in ("python", "portable-exe")
    assert "local-only-test-key" not in res.text


def test_doctor_does_not_call_ocr_in_quick_mode(monkeypatch):
    from localocr.engine import OCRService
    def fail(*args, **kwargs):
        raise AssertionError("quick diagnostics must not load model or infer")
    monkeypatch.setattr(OCRService, "run", fail)
    result = diagnose(deep=False)
    assert result["deep_inference"] == "not_requested"
