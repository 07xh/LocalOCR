"""End-to-end checks for authenticated sample management and reliable annotations."""
from __future__ import annotations
import base64
from io import BytesIO
import json
from zipfile import ZipFile
import pytest
from PIL import Image, ImageDraw
from fastapi.testclient import TestClient
from localocr.api import create_app
from localocr.dataset import DatasetStore, _validate_lines

KEY = "local-test-key"


class FakeOCR:
    def backends(self):
        return {"rapidocr": False, "tesseract": True}

    def run(self, img, engine="auto"):
        from localocr.engine import OCRResult, TextLine
        return OCRResult("test", "document", [TextLine("document", 0.9,
                   [[4, 4], [80, 4], [80, 30], [4, 30]])], img.width, img.height, 5)


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(service=FakeOCR(), token=KEY,
                                 store=DatasetStore(tmp_path / "db")))


def image_base64(text="sample"):
    im = Image.new("RGB", (200, 60), "white")
    ImageDraw.Draw(im).text((15, 20), text, fill="black")
    f = BytesIO()
    im.save(f, "PNG")
    return base64.b64encode(f.getvalue()).decode("ascii")


def call(client, method, path, **kwargs):
    return client.request(method, path, headers={"X-API-Key": KEY}, **kwargs)


def add(client):
    r = call(client, "POST", "/v1/samples", json={"image_base64": image_base64(), "source": "handwritten notes"})
    assert r.status_code == 201, r.text
    return r.json()


def test_studio_served_with_local_assets(client):
    html = client.get("/studio")
    assert html.status_code == 200
    assert "标注工作台" in html.text
    assert "no-store" == html.headers["cache-control"]
    assert "frame-ancestors 'none'" in html.headers["content-security-policy"]
    assert client.get("/assets/studio.js").status_code == 200
    assert client.get("/assets/studio.css").status_code == 200
    report = client.get("/assets/quality_report.js")
    assert report.status_code == 200
    assert "LocalOCRQualityReport" in report.text
    assert '/assets/quality_report.js' in html.text


def test_dataset_requires_auth(client):
    for method, route in [("GET", "/v1/samples"), ("GET", "/v1/datasets/stats"),
                          ("GET", "/v1/datasets/export"), ("POST", "/v1/samples")]:
        assert client.request(method, route).status_code == 401


def test_import_duplicate_and_stats(client):
    first = add(client)
    assert not first["duplicate"]
    second = add(client)
    assert second["duplicate"]
    assert second["id"] == first["id"]
    assert call(client, "GET", "/v1/datasets/stats").json()["total"] == 1
    listing = call(client, "GET", "/v1/samples").json()
    assert listing["total"] == 1 and listing["items"][0]["id"] == first["id"]


def test_image_auth_and_not_found(client):
    item = add(client)
    path = f'/v1/samples/{item["id"]}/image'
    assert client.get(path).status_code == 401
    r = call(client,"GET",path)
    assert r.status_code == 200 and r.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert call(client,"GET","/v1/samples/../../private").status_code in (404, 400)
    assert call(client,"GET","/v1/samples/"+"a"*32).status_code == 404


def test_annotations_and_review_export(client):
    item = add(client)
    sid = item["id"]
    box = [[4,4],[100,4],[100,30],[4,30]]
    r=call(client,"PUT",f"/v1/samples/{sid}/annotations",json={"expected_revision":1,"lines":[{"text":"你好 LocalOCR","box":box}]})
    assert r.status_code == 200, r.text
    revision = r.json()["revision"]
    assert revision == 2
    assert call(client,"GET","/v1/datasets/export?reviewed_only=true").status_code == 200
    z = ZipFile(BytesIO(call(client,"GET","/v1/datasets/export?reviewed_only=true").content))
    assert z.read("labels.jsonl") == b""
    r=call(client,"PATCH",f"/v1/samples/{sid}",json={"expected_revision":revision,"status":"reviewed","split":"val"})
    assert r.status_code == 200 and r.json()["status"] == "reviewed"
    archive = ZipFile(BytesIO(call(client,"GET","/v1/datasets/export?reviewed_only=true").content))
    manifest=json.loads(archive.read("manifest.json"))
    assert manifest["count"] == 1
    labels=[json.loads(x) for x in archive.read("labels.jsonl").decode().splitlines()]
    assert labels[0]["annotations"][0]["text"] == "你好 LocalOCR"
    assert labels[0]["split"] == "val"
    assert archive.read(labels[0]["image"]).startswith(b"\x89PNG")
    # Changing manual annotations always resets review status.
    r=call(client,"PUT",f"/v1/samples/{sid}/annotations",json={"expected_revision":3,"lines":[{"text":"changed","box":box}]})
    assert r.status_code == 200 and r.json()["status"] == "draft"


def test_review_without_labels_rejected(client):
    item=add(client)
    r=call(client,"PATCH",f'/v1/samples/{item["id"]}',json={"expected_revision":1,"status":"reviewed"})
    assert r.status_code == 400


def test_mutation_optimistic_concurrency(client):
    item=add(client)
    sid=item["id"]
    r=call(client,"PATCH",f"/v1/samples/{sid}",json={"expected_revision":1,"split":"train"})
    assert r.status_code == 200
    stale=call(client,"PATCH",f"/v1/samples/{sid}",json={"expected_revision":1,"split":"test"})
    assert stale.status_code == 409
    stale_delete=call(client,"DELETE",f"/v1/samples/{sid}?expected_revision=1")
    assert stale_delete.status_code == 409
    assert call(client,"DELETE",f"/v1/samples/{sid}?expected_revision=2").status_code == 204
    assert call(client,"GET",f"/v1/samples/{sid}").status_code == 404


def test_invalid_boxes_rejected(client):
    item=add(client)
    sid=item["id"]
    for box in (
        [[-1,0],[100,0],[100,20],[0,20]],
        [[0,0],[400,0],[400,20],[0,20]],
        [[0,0],[0,0],[0,0],[0,0]],
    ):
        r=call(client,"PUT",f"/v1/samples/{sid}/annotations",json={"expected_revision":1,"lines":[{"text":"a","box":box}]})
        assert r.status_code in (400,422),r.text


def test_bad_input_and_limits(client):
    assert call(client,"POST","/v1/samples",json={"image_base64":"not!base64"}).status_code == 400
    assert call(client,"GET","/v1/samples?limit=101").status_code == 400
    assert call(client,"GET","/v1/samples?offset=-1").status_code == 400
    assert call(client,"POST","/v1/samples",json={"image_base64":image_base64(),"source":"X"*161}).status_code == 422


def test_suggestion_is_not_saved_as_truth(client):
    item=add(client)
    sid=item["id"]
    r=call(client,"POST",f"/v1/samples/{sid}/suggest")
    assert r.status_code == 200 and r.json()["lines"][0]["text"] == "document"
    assert call(client,"GET",f"/v1/samples/{sid}").json()["annotation_count"] == 0


def test_export_without_review_includes_drafts(client):
    add(client)
    archive=ZipFile(BytesIO(call(client,"GET","/v1/datasets/export?reviewed_only=false").content))
    assert json.loads(archive.read("manifest.json"))["count"] == 1


def test_non_finite_annotation_rejected():
    import math
    from localocr.dataset import DatasetError
    with pytest.raises(DatasetError):
        _validate_lines([{"text": "x", "box": [[0,0],[math.inf,0],[20,20],[0,20]]}],200,60)
