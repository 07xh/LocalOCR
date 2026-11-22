"""Local metadata-only registry for completed PaddleOCR training checkpoints.

Registering is not a model load, model accuracy claim, RapidOCR conversion,
or automatic production deployment. Checkpoint files stay in their run folders.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import threading

from .settings import config_dir
from .training import TrainingError

RUN_ID = re.compile(r"^[a-f0-9]{32}$")
WEIGHTS_FILE = re.compile(r"^[a-zA-Z0-9_.-]+\.pdparams$")
MAX_CHECKPOINT_BYTES = 2 * 1024 * 1024 * 1024


class ModelRegistry:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else config_dir() / "training"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.index = self.root / "models.json"

    def list(self) -> list[dict]:
        with self._lock:
            if not self.index.is_file():
                return []
            records = json.loads(self.index.read_text(encoding="utf-8"))
            if not isinstance(records, list):
                raise TrainingError("Model registry format is invalid")
            return records

    def register(self, run_id: str, filename: str) -> dict:
        if not RUN_ID.fullmatch(run_id) or not WEIGHTS_FILE.fullmatch(filename):
            raise TrainingError("Use a valid training run ID and .pdparams filename")
        folder = (self.root / "runs" / run_id).resolve()
        runs_root = (self.root / "runs").resolve()
        if folder.parent != runs_root or not folder.is_dir():
            raise TrainingError("Local training run was not found")
        status_file = folder / "status.json"
        if not status_file.is_file():
            raise TrainingError("Run has no saved training status")
        status = json.loads(status_file.read_text(encoding="utf-8"))
        if status.get("id") != run_id or status.get("status") != "completed":
            raise TrainingError("Only completed training runs can be registered")
        checkpoint = (folder / filename).resolve()
        if checkpoint.parent != folder or not checkpoint.is_file():
            raise TrainingError("Checkpoint does not exist in the completed run")
        if checkpoint.stat().st_size > MAX_CHECKPOINT_BYTES:
            raise TrainingError("Checkpoint exceeds the registry's 2 GiB limit")

        digest = sha256()
        with checkpoint.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
        key = sha256(f"{run_id}:{filename}:{digest.hexdigest()}".encode()).hexdigest()[:20]
        entry = {
            "id": key, "run_id": run_id, "filename": filename,
            "path": str(checkpoint), "sha256": digest.hexdigest(),
            "size_bytes": checkpoint.stat().st_size,
            "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "state": "registered_unverified",
            "note": "Metadata only. No compatibility, correctness or training quality has been checked.",
        }
        with self._lock:
            old = self.list()
            match = next((item for item in old if item.get("id") == key), None)
            if match is not None:
                return match
            old.append(entry)
            temp = self.root / "models.json.tmp"
            temp.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.index)
        return entry
