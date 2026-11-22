"""PaddleOCR recognition dataset crops and authenticated API regression tests."""
from __future__ import annotations

from io import BytesIO
from zipfile import ZipFile
import json

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
import pytest

from localocr.api import create_app
from localocr.dataset import DatasetStore, DatasetError
from localocr.rec_export import export_recognition_zip, rectify_line

KEY = "rec-data-test-only"


def add_reviewed(store, *, split, color, text="你好 OCR"):
    image = Image.new("RGB", (180, 72), color)
    ImageDraw.Draw(image).rectangle((10, 10, 155, 58), fill="white")
    item = store.add(image)
    item = store.put_annotations(item["id"], item["revision"], [{
        "text": text, "box": [[12, 13], [151, 13], [151, 54], [12, 54]]
    }])
    return store.patch(item["id"], item["revision"], "reviewed", split)


def test_rec_export_crop_format_splits_and_unicode(tmp_path):
    store = DatasetStore(tmp_path / "dataset")
    train = add_reviewed(store, split="train", color="blue")
    add_reviewed(store, split="val", color="yellow", text="English 123")
    add_reviewed(store, split="test", color="red", text="独立评估")
    add_reviewed(store, split="unassigned", color="green", text="skip this")
    with ZipFile(BytesIO(export_recognition_zip(store))) as z:
        for split, expected in (("train", "你好 OCR"), ("val", "English 123"),
                                ("test", "独立评估")):
            label = z.read("rec_gt_" + split + ".txt").decode("utf-8").strip()
            name, text = label.split("\t", 1)
            assert text == expected
            assert name.startswith("rec/" + split + "/")
            with Image.open(BytesIO(z.read(name))) as im:
                assert im.size == (139, 41)
        train_record = z.read("rec_gt_train.txt").decode()
        assert train["id"] in train_record
        assert b"skip this" not in z.read("rec_gt_train.txt")
        manifest = json.loads(z.read("manifest.json"))
        assert manifest["split_counts"] == {"train": 1, "val": 1, "test": 1}
        assert manifest["reviewed_only"] is True
        assert len([x for x in z.namelist() if x.endswith(".png")]) == 3


def test_real_quadrilateral_transform_uses_vertical_extent():
    image = Image.new("RGB", (180, 100), "white")
    points = [[20, 18], [140, 28], [135, 70], [15, 60]]
    crop = rectify_line(image, points)
    assert crop.size[0] >= 120 and crop.size[1] >= 40
    assert crop.mode == "RGB"


def test_rec_ignores_draft_and_rejects_multiline_labels(tmp_path):
    store = DatasetStore(tmp_path)
    pending = store.add(Image.new("RGB", (80, 25), "white"))
    with ZipFile(BytesIO(export_recognition_zip(store))) as z:
        assert z.read("rec_gt_train.txt") == b""
        assert not any(p.endswith(".png") for p in z.namelist())
    assert pending["status"] == "draft"
    add_reviewed(store, split="train", color="blue", text="one\ttwo")
    with pytest.raises(DatasetError, match="tabs/newlines"):
        export_recognition_zip(store)


def test_rec_api_authentication_and_original_routes(tmp_path):
    store = DatasetStore(tmp_path)
    add_reviewed(store, split="train", color="blue")
    client = TestClient(create_app(token=KEY, store=store))
    path = "/v1/datasets/export/paddle-rec"
    assert client.get(path).status_code == 401
    response = client.get(path, headers={"X-API-Key": KEY})
    assert response.status_code == 200
    assert "application/zip" in response.headers["content-type"]
    with ZipFile(BytesIO(response.content)) as z:
        assert "rec_gt_train.txt" in z.namelist()
    original = client.get("/v1/datasets/export/paddle-det", headers={"X-API-Key": KEY})
    assert original.status_code == 200
    assert client.post("/v1/ocr", json={"image_base64": "%%"}).status_code == 401
