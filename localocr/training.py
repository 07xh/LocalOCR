"""Explicit, local PaddleOCR v5 recognition fine-tuning job runner.

Does not download weights or run anything remotely. It invokes only the
official local PaddleOCR tools/train.py entrypoint with a fixed config.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import threading
from uuid import uuid4

from .settings import config_dir


class TrainingError(ValueError):
    pass


def _verified_labels(root: Path, label_file: str) -> int:
    path = root / label_file
    if not path.is_file():
        raise TrainingError("Missing " + label_file + " in extracted recognition dataset")
    count = 0
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line:
            continue
        if "\t" not in line:
            raise TrainingError("Invalid recognition label: expected path TAB text")
        rel_path, text = line.split("\t", 1)
        rel = Path(rel_path)
        if not text.strip() or rel.is_absolute() or ".." in rel.parts:
            raise TrainingError("Invalid or unsafe recognition label")
        image_path = (root / rel).resolve()
        if not image_path.is_relative_to(root) or not image_path.is_file():
            raise TrainingError("Recognition label references a missing/unsafe image")
        count += 1
    return count


def build_plan(
    paddle_repo: str, dataset_dir: str, pretrained_model: str,
    *, epochs: int = 10, batch_size: int = 4, use_gpu: bool = False,
    output_dir: Path | None = None,
    resume_run_id: str | None = None, resume_checkpoint: str = "latest",
    resume_root: Path | None = None,
) -> dict:
    """Validate all local inputs and build a fixed, shell-free command."""
    repo = Path(paddle_repo).expanduser().resolve()
    data = Path(dataset_dir).expanduser().resolve()
    weights = Path(pretrained_model).expanduser().resolve()
    if not repo.is_dir() or not (repo / "tools" / "train.py").is_file():
        raise TrainingError("Choose a checked-out official PaddleOCR repository")
    config_name = "configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml"
    if not (repo / config_name).is_file():
        raise TrainingError("PaddleOCR v5 mobile-rec config is missing")
    if not data.is_dir():
        raise TrainingError("Recognition data directory does not exist")
    if not weights.is_file() or weights.suffix != ".pdparams":
        raise TrainingError("Choose a local .pdparams pretrained weight file")
    if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= 50:
        raise TrainingError("epochs must be 1–50")
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or not 1 <= batch_size <= 32:
        raise TrainingError("batch_size must be 1–32")
    train = _verified_labels(data, "rec_gt_train.txt")
    val = _verified_labels(data, "rec_gt_val.txt")
    test = _verified_labels(data, "rec_gt_test.txt")
    if train < 2 or val < 1:
        raise TrainingError("Need at least 2 training crops and 1 validation crop")
    if train < batch_size:
        raise TrainingError("Training crops must be >= batch size")

    # Resume is deliberately restricted to checkpoints in an existing local
    # run and requires the matching optimizer and epoch metadata. A bare
    # pretrained .pdparams file is NOT a resumable training checkpoint.
    config_identity = {
        "paddle_repo": str(repo), "dataset_dir": str(data),
        "pretrained_model": str(weights), "batch_size": batch_size,
        "use_gpu": use_gpu, "config_file": config_name,
        "train_labels_sha256": sha256((data / "rec_gt_train.txt").read_bytes()).hexdigest(),
        "val_labels_sha256": sha256((data / "rec_gt_val.txt").read_bytes()).hexdigest(),
    }
    source_run = None
    checkpoint_prefix = None
    if resume_run_id is not None:
        if not isinstance(resume_run_id, str) or not re.fullmatch(r"[a-f0-9]{32}", resume_run_id):
            raise TrainingError("Resume run ID must be a 32-digit local run identifier")
        if resume_checkpoint not in ("latest", "best_accuracy"):
            raise TrainingError("Resume checkpoint must be latest or best_accuracy")
        root = (resume_root or config_dir() / "training" / "runs").resolve()
        folder = (root / resume_run_id).resolve()
        if folder.parent != root or not folder.is_dir():
            raise TrainingError("Resume source run does not exist")
        status_file = folder / "status.json"
        try:
            prior = json.loads(status_file.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise TrainingError("Resume source has no valid saved status") from exc
        if (prior.get("id") != resume_run_id
                or prior.get("status") not in ("failed", "cancelled", "completed")):
            raise TrainingError("Cannot resume an active or unverified training run")
        if prior.get("training_config") != config_identity:
            raise TrainingError("Resume configuration or training labels have changed")
        if prior.get("status") == "completed" and epochs <= prior.get("epochs", 0):
            raise TrainingError("Completed run requires a greater target epoch count")
        checkpoint_prefix = (folder / resume_checkpoint).resolve()
        if checkpoint_prefix.parent != folder:
            raise TrainingError("Resume checkpoint must remain inside its source run")
        for extension in (".pdparams", ".pdopt", ".states"):
            artifact = Path(str(checkpoint_prefix) + extension)
            if not artifact.is_file() or artifact.resolve().parent != folder:
                raise TrainingError("Resume checkpoint lacks safe " + extension + " file")
        source_run = {"run_id": resume_run_id, "checkpoint": resume_checkpoint}

    # Model configurations are trusted files in the local official PaddleOCR checkout.
    # All paths are JSON-string encoded as YAML-compatible string/list values.
    output = (output_dir or config_dir() / "training" / "runs" / uuid4().hex).resolve()
    options = {
        "Global.pretrained_model": "" if checkpoint_prefix else str(weights),
        "Global.checkpoints": str(checkpoint_prefix) if checkpoint_prefix else "",
        "Global.save_model_dir": str(output),
        "Global.use_gpu": use_gpu,
        "Global.distributed": False,
        "Global.epoch_num": epochs,
        "Global.save_epoch_step": 1,  # keep actual model/optimizer/epoch state for resume
        "Train.dataset.data_dir": str(data),
        "Train.dataset.label_file_list": [str(data / "rec_gt_train.txt")],
        "Eval.dataset.data_dir": str(data),
        "Eval.dataset.label_file_list": [str(data / "rec_gt_val.txt")],
        "Train.sampler.first_bs": batch_size,
        "Train.loader.batch_size_per_card": batch_size,
        "Eval.loader.batch_size_per_card": batch_size,
        "Train.loader.num_workers": 0,
        "Eval.loader.num_workers": 0,
    }
    args = [sys.executable, "tools/train.py", "-c", config_name, "-o"]
    args.extend(f"{key}={json.dumps(value, ensure_ascii=False)}" for key, value in options.items())
    return {
        "cwd": str(repo), "args": args, "output_dir": str(output),
        "train_count": train, "val_count": val, "test_count": test,
        "epochs": epochs, "batch_size": batch_size, "use_gpu": use_gpu,
        "training_config": config_identity, "resume_from": source_run,
        "note": "PaddleOCR training process requires PaddlePaddle in this Python environment. "
                "Test split is reserved and never passed to the trainer.",
    }


def _resume_candidates(folder: Path) -> list[str]:
    """Report checkpoints that contain model, optimizer, and epoch state."""
    return [
        prefix for prefix in ("latest", "best_accuracy")
        if all(
            (p := folder / (prefix + suffix)).is_file()
            and p.resolve().parent == folder.resolve()
            for suffix in (".pdparams", ".pdopt", ".states")
        )
    ]


class TrainingManager:
    """Single active local training process with a persistent, bounded log."""

    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root is not None else config_dir() / "training"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._process: subprocess.Popen | None = None
        self._record: dict | None = None
        self._log_handle = None

    def _persist(self) -> None:
        """Atomic metadata update: only progress, run config and output path."""
        if self._record is None:
            return
        output = Path(self._record["output_dir"])
        path = output / "status.json"
        tmp = output / "status.json.tmp"
        tmp.write_text(json.dumps(self._record, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(path)

    def history(self, limit: int = 20) -> list[dict]:
        """Return recent local runs; stale running records are reported as unknown."""
        limit = min(50, max(1, limit))
        entries = []
        root = self.root / "runs"
        if not root.is_dir():
            return entries
        for folder in root.iterdir():
            if not folder.is_dir() or not re.fullmatch("[a-f0-9]{32}", folder.name):
                continue
            path = folder / "status.json"
            if not path.is_file():
                continue
            try:
                item = json.loads(path.read_text(encoding="utf-8"))
                if item.get("id") != folder.name:
                    continue
                if self._record is None or self._record.get("id") != folder.name:
                    if item.get("status") in ("running", "cancel_requested"):
                        item["status"] = "unknown_after_restart"
                item["resume_candidates"] = (
                    _resume_candidates(folder)
                    if item.get("status") in ("completed", "failed", "cancelled") else []
                )
                entries.append(item)
            except (ValueError, OSError):
                continue
        entries.sort(key=lambda x: x.get("started_at", ""), reverse=True)
        return entries[:limit]

    def start(self, plan: dict) -> dict:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                raise TrainingError("A training task is already running")
            self._close_log()
            out = Path(plan["output_dir"]).resolve()
            out.mkdir(parents=True, exist_ok=False)
            log_file = out / "train.log"
            self._log_handle = log_file.open("w", encoding="utf-8")
            try:
                kwargs = {"cwd": plan["cwd"], "stdin": subprocess.DEVNULL,
                          "stdout": self._log_handle, "stderr": subprocess.STDOUT,
                          "shell": False}
                if os.name != "nt":
                    kwargs["start_new_session"] = True
                else:
                    kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
                proc = subprocess.Popen(plan["args"], **kwargs)
            except (OSError, ValueError):
                self._close_log()
                raise
            self._process = proc
            self._record = {
                "id": out.name, "status": "running", "pid": proc.pid,
                "started_at": datetime.now(timezone.utc).isoformat(),
                "output_dir": str(out), "exit_code": None,
                "train_count": plan["train_count"], "val_count": plan["val_count"],
                "test_count": plan["test_count"], "epochs": plan["epochs"],
                "training_config": plan.get("training_config"),
                "resume_from": plan.get("resume_from"),
            }
            self._persist()
            return self.status()

    def status(self) -> dict:
        with self._lock:
            if self._record is None:
                return {"status": "idle"}
            if self._process is not None:
                code = self._process.poll()
                if code is not None and self._record["status"] in ("running", "cancel_requested"):
                    self._record["status"] = (
                        "cancelled" if self._record["status"] == "cancel_requested"
                        else ("completed" if code == 0 else "failed")
                    )
                    self._record["exit_code"] = code
                    self._record["finished_at"] = datetime.now(timezone.utc).isoformat()
                    self._persist()
                    self._close_log()
            result = dict(self._record)
            log = Path(result["output_dir"]) / "train.log"
            if log.is_file():
                # Avoid loading large training logs into memory.
                with log.open("rb") as stream:
                    stream.seek(max(0, log.stat().st_size - 4096))
                    result["log_tail"] = stream.read().decode("utf-8", "replace")[-3500:]
            # Only show concrete local model checkpoints, not claimed metrics.
            root = Path(result["output_dir"])
            result["model_files"] = sorted(
                p.name for p in root.glob("*.pdparams") if p.is_file()
            )[:50]
            result["resume_candidates"] = (
                _resume_candidates(root)
                if result.get("status") in ("completed", "failed", "cancelled") else []
            )
            # PaddleOCR outputs epoch: [N/TOTAL] in its normal training log.
            # Parsed progress is informative, not a guarantee of final quality.
            tail = result.get("log_tail", "")
            matches = re.findall(r"epoch:\s*\[(\d+)\s*/\s*(\d+)\]", tail)
            if matches:
                current, total = map(int, matches[-1])
                if total > 0:
                    result["epoch_current"] = min(current, total)
                    result["epoch_total"] = total
                    result["epoch_percent"] = round(100 * min(current, total) / total, 1)
            return result

    def cancel(self) -> dict:
        with self._lock:
            if self._process is None or self._process.poll() is not None:
                raise TrainingError("No active training task")
            if os.name != "nt":
                os.killpg(self._process.pid, signal.SIGTERM)
            else:
                self._process.terminate()
            self._record["status"] = "cancel_requested"
            self._persist()
            return self.status()

    def _close_log(self):
        if self._log_handle is not None:
            self._log_handle.close()
            self._log_handle = None
