"""Local OCR accuracy measurement on manually reviewed held-out crops."""
from __future__ import annotations

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from localocr.api import create_app
from localocr.dataset import DatasetStore
from localocr.engine import OCRResult, EngineUnavailable

KEY = "test-only-reviewed-evaluation"
ROUTE = "/v1/evaluation/reviewed-test"
BOX = [[8, 8], [92, 8], [92, 35], [8, 35]]


class FakeOCR:
    def __init__(self):
        self.calls = []

    def run(self, image, engine="auto"):
        self.calls.append((image.size, engine))
        if engine == "rapidocr":
            raise EngineUnavailable("not installed")
        return OCRResult("fake", "Alpha", [], image.width, image.height, 8)

    def backends(self):
        return {"rapidocr": False, "tesseract": True}


def sample(store, *, color, text, status="reviewed", split="test"):
    picture = Image.new("RGB", (110, 45), color)
    ImageDraw.Draw(picture).text((8, 8), text, fill="black")
    item = store.add(picture)
    item = store.put_annotations(item["id"], item["revision"],
                                 [{"text": text, "box": BOX}])
    return store.patch(item["id"], item["revision"], status, split)


def client(tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    ocr = FakeOCR()
    return TestClient(create_app(service=ocr, store=store, token=KEY)), store, ocr


def post(c, payload=None, key=KEY):
    headers = {"X-API-Key": key} if key else {}
    return c.post(ROUTE, headers=headers, json=payload or {})


def test_test_split_only_accuracy_latency_and_no_mutations(tmp_path):
    c, store, ocr = client(tmp_path)
    yes = sample(store, color="white", text="Alpha")
    no = sample(store, color="yellow", text="Alphx")
    sample(store, color="lightblue", text="Other", split="train")
    sample(store, color="lightgreen", text="Other", status="draft")

    before = [store.get(yes["id"]), store.get(no["id"])]
    r = post(c)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["split"] == "test" and data["reviewed_only"] is True
    assert data["evaluated_samples"] == 2 and data["evaluated_regions"] == 2
    assert data["available_test_samples"] == 2 and data["has_more"] is False
    assert data["exact_matches"] == 1 and data["exact_match_rate"] == 0.5
    assert data["edit_errors"] == 1 and data["cer"] == 0.1
    assert data["inference_ms_total"] == 16 and data["actual_engines"] == ["fake"]
    assert len(ocr.calls) == 2
    assert data["error_examples"][0]["sample_id"] == no["id"]
    assert "Alpha" not in str(data["error_examples"])
    assert [store.get(yes["id"]), store.get(no["id"])] == before


def test_auth_bounds_pages_and_engine_errors(tmp_path):
    c, store, ocr = client(tmp_path)
    assert post(c, key=None).status_code == 401
    assert post(c).status_code == 400  # empty held-out test set
    sample(store, color="white", text="Alpha")
    sample(store, color="yellow", text="Alpha")
    assert post(c, {"limit": 21}).status_code == 422
    assert post(c, {"offset": -1}).status_code == 422
    page = post(c, {"limit": 1, "offset": 0})
    assert page.status_code == 200
    assert page.json()["evaluated_regions"] == 1
    assert page.json()["has_more"] is True
    assert page.json()["next_offset"] == 1
    assert post(c, {"offset": 50}).status_code == 400
    assert post(c, {"engine": "rapidocr"}).status_code == 503


def test_region_bound_rejected_before_any_inference(tmp_path):
    c, store, ocr = client(tmp_path)
    picture = Image.new("RGB", (110, 45), "white")
    item = store.add(picture)
    labels = [{"text": "A", "box": BOX} for _ in range(41)]
    item = store.put_annotations(item["id"], item["revision"], labels)
    store.patch(item["id"], item["revision"], "reviewed", "test")
    r = post(c)
    assert r.status_code == 400 and "40" in r.text
    assert ocr.calls == []
