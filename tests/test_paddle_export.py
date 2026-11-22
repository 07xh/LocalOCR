"""PPOCRLabel / PaddleOCR detection ZIP compatibility tests."""
from __future__ import annotations

from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from localocr.api import create_app
from localocr.dataset import DatasetStore, DatasetError
from localocr.paddle_export import export_detection_zip

KEY = "test-only-key"


def sample(store: DatasetStore, *, split: str = "train", review: bool = True,
           text: str = "你好 OCR", color: str = "white") -> dict:
    image = Image.new("RGB", (240, 80), color)
    ImageDraw.Draw(image).text((10, 15), "LOCAL", fill="black")
    saved = store.add(image, "private original file name must not leak")
    if not review:
        return saved
    saved = store.put_annotations(saved["id"], saved["revision"], [{
        "text": text,
        "box": [[4, 3], [150, 3], [150, 45], [4, 45]],
    }])
    saved = store.patch(saved["id"], saved["revision"], "reviewed", split)
    return saved


def test_export_has_real_ppocrlabel_fields_and_split(tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    item = sample(store)
    blob = export_detection_zip(store)
    with ZipFile(BytesIO(blob)) as z:
        names = set(z.namelist())
        assert {"Label.txt", "det/train.txt", "det/val.txt",
                "det/test.txt", "manifest.json"} <= names
        path, serialized = z.read("Label.txt").decode().strip().split("\t", 1)
        assert path == f'images/{item["id"]}.png'
        assert z.read(path).startswith(b"\x89PNG")
        labels = json.loads(serialized)
        assert labels == [{"transcription": "你好 OCR",
                           "points": [[4, 3], [150, 3], [150, 45], [4, 45]],
                           "difficult": False}]
        assert z.read("det/train.txt") == z.read("Label.txt")
        assert z.read("det/val.txt") == b""
        assert z.read("det/test.txt") == b""
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["split_counts"]["train"] == 1
        assert b"private original file name" not in blob


def test_drafts_excluded_unassigned_not_used_for_training(tmp_path):
    store = DatasetStore(tmp_path)
    reviewed = sample(store, split="unassigned", color="white")
    draft = sample(store, review=False, color="lightblue")
    with ZipFile(BytesIO(export_detection_zip(store))) as z:
        assert z.read("Label.txt").count(b"\n") == 1
        assert f'images/{reviewed["id"]}.png' in z.namelist()
        assert f'images/{draft["id"]}.png' not in z.namelist()
        for split in ("train", "val", "test"):
            assert z.read(f"det/{split}.txt") == b""


def test_api_authentication_and_original_export_unchanged(tmp_path):
    store = DatasetStore(tmp_path)
    sample(store, split="val")
    client = TestClient(create_app(token=KEY, store=store))
    url = "/v1/datasets/export/paddle-det"
    assert client.get(url).status_code == 401
    response = client.get(url, headers={"X-API-Key": KEY})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/zip")
    with ZipFile(BytesIO(response.content)) as z:
        assert z.read("det/val.txt") == z.read("Label.txt")
    old = client.get("/v1/datasets/export", headers={"X-API-Key": KEY})
    assert old.status_code == 200
    with ZipFile(BytesIO(old.content)) as z:
        assert "labels.jsonl" in z.namelist()


def test_missing_image_produces_clear_error(tmp_path):
    store = DatasetStore(tmp_path)
    item = sample(store)
    (store.images / (item["id"] + ".png")).unlink()
    import pytest
    with pytest.raises(DatasetError, match="missing"):
        export_detection_zip(store)


def test_empty_export_is_valid(tmp_path):
    store = DatasetStore(tmp_path)
    with ZipFile(BytesIO(export_detection_zip(store))) as z:
        assert z.read("Label.txt") == b""
        assert json.loads(z.read("manifest.json"))["count"] == 0
