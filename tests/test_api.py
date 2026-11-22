import base64
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from localocr.api import create_app
from localocr.engine import OCRResult, TextLine, OCRService

TOKEN = "test-key-for-local-unit-tests"


class FakeEngine:
    def backends(self):
        return {"rapidocr": False, "tesseract": True}

    def run(self, img, engine="auto"):
        return OCRResult("test", "Test 123", [TextLine("Test 123", 0.99, [[0, 0], [20, 0], [20, 10], [0, 10]])], img.width, img.height, 1)


def image_b64():
    b = BytesIO()
    Image.new("RGB", (60, 20), "white").save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


def client():
    return TestClient(create_app(service=FakeEngine(), token=TOKEN))


def test_health():
    response = client().get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_authorization_required():
    response = client().post("/v1/ocr", json={"image_base64": image_b64()})
    assert response.status_code == 401


def test_authorization_bad():
    response = client().post("/v1/ocr", headers={"X-API-Key": "bad"}, json={"image_base64": image_b64()})
    assert response.status_code == 401


def test_recognize_and_schema():
    response = client().post("/v1/ocr", headers={"X-API-Key": TOKEN}, json={"image_base64": image_b64()})
    assert response.status_code == 200, response.text
    d = response.json()
    assert d["text"] == "Test 123"
    assert d["lines"][0]["confidence"] == 0.99
    assert (d["width"], d["height"]) == (60, 20)


def test_engines():
    response = client().get("/v1/engines", headers={"X-API-Key": TOKEN})
    assert response.json()["available"]["tesseract"] is True


def test_reject_invalid_image():
    response = client().post("/v1/ocr", headers={"X-API-Key": TOKEN}, json={"image_base64": "aW52YWxpZA=="})
    assert response.status_code == 400


def test_reject_invalid_base64():
    response = client().post("/v1/ocr", headers={"X-API-Key": TOKEN}, json={"image_base64": "%%%%"})
    assert response.status_code == 400


def test_reject_unallowed_engine():
    response = client().post("/v1/ocr", headers={"X-API-Key": TOKEN}, json={"image_base64": image_b64(), "engine": "none"})
    assert response.status_code == 422


def test_reject_large_encoded_data():
    response = client().post("/v1/ocr", headers={"X-API-Key": TOKEN}, json={"image_base64": "A" * 11_500_000})
    assert response.status_code == 400


def test_engine_auto_resolves(monkeypatch):
    monkeypatch.setattr(OCRService, 'backends', staticmethod(lambda: {'rapidocr': False, 'tesseract': True}))
    assert OCRService().resolve("auto") == "tesseract"
