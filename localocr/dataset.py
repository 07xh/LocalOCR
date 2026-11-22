"""Private local image/annotation store for supervised OCR data preparation.

No network fetching, no automatic truth labels, no reliance on third-party websites.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import math
import json
from pathlib import Path
import re
import sqlite3
import threading
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

from PIL import Image

from .image_io import InvalidImage
from .settings import config_dir

ID = re.compile(r"^[0-9a-f]{32}$")
SPLITS = {"unassigned", "train", "val", "test"}
STATUSES = {"draft", "reviewed"}
MAX_IMAGES_FOR_EXPORT = 150
MAX_EXPORT_BYTES = 128 * 1024 * 1024
MAX_STORED_PNG = 32 * 1024 * 1024
MAX_LINES = 512


class DatasetError(ValueError):
    pass


class MissingSample(DatasetError):
    pass


class VersionConflict(DatasetError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _encode_png(image: Image.Image) -> bytes:
    # Decoding upstream already enforces pixel/format limits and applies EXIF transpose.
    out = BytesIO()
    image.convert("RGB").save(out, "PNG", optimize=False)
    data = out.getvalue()
    if len(data) > MAX_STORED_PNG:
        raise InvalidImage("Decoded PNG exceeds the 32 MiB local dataset limit")
    return data


def _validate_id(sample_id: str) -> None:
    if not ID.fullmatch(sample_id):
        raise MissingSample("Sample not found")


def _validate_lines(lines: list, width: int, height: int) -> list[dict]:
    if not isinstance(lines, list) or len(lines) > MAX_LINES:
        raise DatasetError("Annotations must be a list of up to 512 text regions")
    result = []
    for line in lines:
        if not isinstance(line, dict):
            raise DatasetError("Invalid annotation entry")
        text = line.get("text")
        box = line.get("box")
        if not isinstance(text, str) or not text.strip() or len(text) > 1024:
            raise DatasetError("Annotation text must contain 1–1024 characters")
        if (not isinstance(box, list) or len(box) != 4 or
                any(not isinstance(p, list) or len(p) != 2 for p in box)):
            raise DatasetError("Annotation box must contain four [x,y] points")
        points = []
        for x, y in box:
            if (isinstance(x, bool) or isinstance(y, bool) or
                    not isinstance(x, (int, float)) or not isinstance(y, (int, float)) or
                    not math.isfinite(x) or not math.isfinite(y) or
                    not (0 <= x <= width and 0 <= y <= height)):
                raise DatasetError("Annotation point outside image")
            points.append([round(x), round(y)])
        if (max(p[0] for p in points) - min(p[0] for p in points) < 2 or
                max(p[1] for p in points) - min(p[1] for p in points) < 2):
            raise DatasetError("Annotation box is too small")
        result.append({"text": text.strip(), "box": points})
    return result


class DatasetStore:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else config_dir() / "dataset"
        self.root.mkdir(parents=True, exist_ok=True)
        self.images = self.root / "images"
        self.images.mkdir(parents=True, exist_ok=True)
        self.db = self.root / "samples.sqlite3"
        self._lock = threading.RLock()
        with self._connect() as con:
            con.execute("""CREATE TABLE IF NOT EXISTS samples (
                id TEXT PRIMARY KEY,
                digest TEXT NOT NULL UNIQUE,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                source TEXT NOT NULL,
                split TEXT NOT NULL,
                status TEXT NOT NULL,
                annotations TEXT NOT NULL,
                revision INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""")
            con.execute("CREATE INDEX IF NOT EXISTS idx_samples_created ON samples(created_at)")

    @contextmanager
    def _connect(self):
        con = sqlite3.connect(self.db, timeout=20)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    @staticmethod
    def _as_dict(row: sqlite3.Row) -> dict:
        item = dict(row)
        item.pop("digest")
        item["annotations"] = json.loads(item["annotations"])
        item["annotation_count"] = len(item["annotations"])
        return item

    def add(self, image: Image.Image, source: str = "local") -> dict:
        if not isinstance(source, str) or len(source) > 160:
            raise DatasetError("Source description exceeds 160 characters")
        binary = _encode_png(image)
        digest = sha256(binary).hexdigest()
        with self._lock:
            with self._connect() as con:
                old = con.execute("SELECT * FROM samples WHERE digest=?", (digest,)).fetchone()
                if old:
                    return {**self._as_dict(old), "duplicate": True}
                sid = uuid4().hex
                # Generated UUID-only path; never use user filename/path as a destination.
                (self.images / f"{sid}.png").write_bytes(binary)
                now = _now()
                con.execute("""INSERT INTO samples
                    (id,digest,width,height,source,split,status,annotations,revision,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (sid, digest, image.width, image.height, source.strip() or "local",
                     "unassigned", "draft", "[]", 1, now, now))
                row = con.execute("SELECT * FROM samples WHERE id=?", (sid,)).fetchone()
                return {**self._as_dict(row), "duplicate": False}

    def get(self, sample_id: str) -> dict:
        _validate_id(sample_id)
        with self._connect() as con:
            row = con.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone()
        if row is None:
            raise MissingSample("Sample not found")
        return self._as_dict(row)

    def image(self, sample_id: str) -> bytes:
        self.get(sample_id)
        try:
            return (self.images / f"{sample_id}.png").read_bytes()
        except FileNotFoundError as e:
            raise MissingSample("Sample image missing") from e

    def list(self, limit: int = 50, offset: int = 0) -> dict:
        with self._connect() as con:
            total = con.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
            rows = con.execute("SELECT * FROM samples ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                               (limit, offset)).fetchall()
        return {"total": total, "items": [self._as_dict(r) for r in rows]}

    def reviewed_test_page(self, limit: int = 5, offset: int = 0) -> dict:
        """Stable, paginated snapshot of human-reviewed held-out test samples."""
        if not isinstance(limit, int) or not 1 <= limit <= 20 or not isinstance(offset, int) or offset < 0:
            raise DatasetError("limit must be 1..20 and offset must be non-negative")
        with self._connect() as con:
            # A single read transaction prevents counting one revision and
            # returning another revision if the editor saves during this call.
            con.execute("BEGIN")
            versions = con.execute(
                """SELECT id,revision FROM samples
                   WHERE status='reviewed' AND split='test' ORDER BY id ASC"""
            ).fetchall()
            rows = con.execute(
                """SELECT * FROM samples WHERE status='reviewed' AND split='test'
                   ORDER BY id ASC LIMIT ? OFFSET ?""", (limit, offset)
            ).fetchall()
        fingerprint = sha256(json.dumps(
            [[r["id"], r["revision"]] for r in versions],
            separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        return {"total": len(versions),
                "fingerprint": fingerprint,
                "items": [self._as_dict(r) for r in rows]}

    def put_annotations(self, sample_id: str, expected_revision: int, lines: list) -> dict:
        with self._lock:
            with self._connect() as con:
                row = con.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone()
                if row is None:
                    raise MissingSample("Sample not found")
                if row["revision"] != expected_revision:
                    raise VersionConflict("Sample changed in another editor; refresh before saving")
                normalized = _validate_lines(lines, row["width"], row["height"])
                # Editing an approved record intentionally returns it to draft status.
                con.execute("""UPDATE samples SET annotations=?,status='draft',revision=revision+1,updated_at=?
                           WHERE id=?""", (json.dumps(normalized, ensure_ascii=False), _now(), sample_id))
                return self._as_dict(con.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone())

    def patch(self, sample_id: str, expected_revision: int,
              status: str | None = None, split: str | None = None, source: str | None = None) -> dict:
        with self._lock:
            with self._connect() as con:
                row = con.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone()
                if row is None:
                    raise MissingSample("Sample not found")
                if row["revision"] != expected_revision:
                    raise VersionConflict("Sample changed in another editor; refresh before saving")
                new_status = status or row["status"]
                new_split = split or row["split"]
                new_source = row["source"] if source is None else source.strip()
                if new_status not in STATUSES or new_split not in SPLITS:
                    raise DatasetError("Unknown status or dataset split")
                if len(new_source) > 160:
                    raise DatasetError("Source description exceeds 160 characters")
                if new_status == "reviewed" and not json.loads(row["annotations"]):
                    raise DatasetError("Add and save annotations before marking reviewed")
                con.execute("""UPDATE samples SET source=?, status=?, split=?, revision=revision+1,updated_at=?
                           WHERE id=?""", (new_source or "local", new_status, new_split, _now(), sample_id))
                return self._as_dict(con.execute("SELECT * FROM samples WHERE id=?", (sample_id,)).fetchone())

    def delete(self, sample_id: str, expected_revision: int) -> None:
        with self._lock:
            with self._connect() as con:
                row = con.execute("SELECT revision FROM samples WHERE id=?", (sample_id,)).fetchone()
                if row is None:
                    raise MissingSample("Sample not found")
                if row["revision"] != expected_revision:
                    raise VersionConflict("Sample changed in another editor; refresh before deleting")
                con.execute("DELETE FROM samples WHERE id=?", (sample_id,))
            (self.images / f"{sample_id}.png").unlink(missing_ok=True)

    def stats(self) -> dict:
        with self._connect() as con:
            status = dict(con.execute("SELECT status,COUNT(*) FROM samples GROUP BY status").fetchall())
            split = dict(con.execute("SELECT split,COUNT(*) FROM samples GROUP BY split").fetchall())
        return {"total": sum(status.values()), "draft": status.get("draft", 0),
                "reviewed": status.get("reviewed", 0), "splits": {k: split.get(k, 0) for k in sorted(SPLITS)}}

    def export_zip(self, reviewed_only: bool = True) -> bytes:
        with self._connect() as con:
            where = "WHERE status='reviewed'" if reviewed_only else ""
            rows = con.execute(f"SELECT * FROM samples {where} ORDER BY id").fetchall()
        if len(rows) > MAX_IMAGES_FOR_EXPORT:
            raise DatasetError(f"Export limited to {MAX_IMAGES_FOR_EXPORT} images per operation")
        estimated_bytes = sum((self.images / f'{row["id"]}.png').stat().st_size for row in rows)
        if estimated_bytes > MAX_EXPORT_BYTES:
            raise DatasetError("Export exceeds 128 MiB; export fewer images in smaller batches")
        out = BytesIO()
        with ZipFile(out, "w", ZIP_DEFLATED, compresslevel=3) as z:
            labels = []
            for row in rows:
                item = self._as_dict(row)
                img = self.image(item["id"])
                z.writestr(f'images/{item["id"]}.png', img)
                labels.append(json.dumps({"image": f'images/{item["id"]}.png',
                                          "split": item["split"], "source": item["source"],
                                          "status": item["status"], "annotations": item["annotations"]},
                                         ensure_ascii=False))
            z.writestr("labels.jsonl", "\n".join(labels) + ("\n" if labels else ""))
            z.writestr("manifest.json", json.dumps({"format": "LocalOCR dataset 1.0",
                                                    "count": len(rows), "reviewed_only": reviewed_only,
                                                    "generated_at": _now(),
                                                    "note": "Human reviewed labels are required before model training."},
                                                   ensure_ascii=False, indent=2))
        return out.getvalue()
