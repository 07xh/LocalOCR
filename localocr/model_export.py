"""Safely export a completed local PaddleOCR checkpoint to static inference files.

The output is staged metadata only: no ONNX conversion, RapidOCR activation,
accuracy claim or model download occurs here.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess

from .models import ModelRegistry, RUN_ID, WEIGHTS_FILE
from .training import TrainingError

MODEL_ID = re.compile(r"^[0-9a-f]{20}$")
PYTHON_NAME = re.compile(r"python(?:w)?(?:[0-9]+(?:\.[0-9]+)?)?(?:\.exe)?$", re.IGNORECASE)
CONFIG_FILE = "configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml"
MAX_EXPORT_SECONDS = 1800


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_paddle_export_plan(registry: ModelRegistry, model_id: str, training_python: str) -> dict:
    """Build a fixed, shell-free export command from a registered checkpoint.

    The user supplies only an existing external Python interpreter; the
    repository, run, weights and config come from verified local metadata.
    """
    if not MODEL_ID.fullmatch(model_id):
        raise TrainingError("Invalid registered model ID")
    entry = next((item for item in registry.list() if item.get("id") == model_id), None)
    if entry is None or entry.get("state") != "registered_unverified":
        raise TrainingError("Only registered, unverified checkpoints may be exported")
    run_id, filename = entry.get("run_id"), entry.get("filename")
    if not isinstance(run_id, str) or not RUN_ID.fullmatch(run_id):
        raise TrainingError("Invalid training run ID in model registry")
    if not isinstance(filename, str) or not WEIGHTS_FILE.fullmatch(filename):
        raise TrainingError("Invalid checkpoint filename in model registry")
    runs_root = (registry.root / "runs").resolve()
    run = (runs_root / run_id).resolve()
    checkpoint = (run / filename).resolve()
    if run.parent != runs_root or checkpoint.parent != run or not checkpoint.is_file():
        raise TrainingError("Registered checkpoint is missing or outside its training run")
    if _sha256(checkpoint) != entry.get("sha256"):
        raise TrainingError("Registered checkpoint changed since its SHA-256 was recorded")
    try:
        status = json.loads((run / "status.json").read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise TrainingError("Training run has no valid status record") from exc
    if not isinstance(status, dict) or status.get("id") != run_id or status.get("status") != "completed":
        raise TrainingError("Model export requires a completed training run")
    training_config = status.get("training_config")
    if not isinstance(training_config, dict) or not isinstance(training_config.get("paddle_repo"), str):
        raise TrainingError("Completed training run lacks a reproducible PaddleOCR source directory")
    repo = Path(training_config["paddle_repo"]).expanduser().resolve()
    if not (repo / "tools" / "export_model.py").is_file() or not (repo / CONFIG_FILE).is_file():
        raise TrainingError("Original PaddleOCR checkout does not contain required v5 export tools")
    python = Path(training_python).expanduser().resolve()
    if not python.is_file() or PYTHON_NAME.fullmatch(python.name) is None:
        raise TrainingError("Choose an existing external Python interpreter")
    dest = (registry.root / "exports" / model_id).resolve()
    if dest.parent != (registry.root / "exports").resolve():
        raise TrainingError("Unsafe export destination")
    if dest.exists():
        raise TrainingError("Export destination already exists; keep or inspect the prior attempt")
    inference = dest / "inference"
    args = [
        str(python), "tools/export_model.py", "-c", CONFIG_FILE, "-o",
        "Global.pretrained_model=" + json.dumps(str(checkpoint), ensure_ascii=False),
        "Global.save_inference_dir=" + json.dumps(str(inference), ensure_ascii=False),
    ]
    return {
        "model_id": model_id, "run_id": run_id, "source_checkpoint_sha256": entry["sha256"],
        "cwd": str(repo), "args": args, "output_dir": str(dest),
        "inference_dir": str(inference),
        "note": "Static Paddle inference export only. No ONNX validation or model activation.",
    }


def export_paddle_checkpoint(
    registry: ModelRegistry, model_id: str, training_python: str,
    *, timeout: int = MAX_EXPORT_SECONDS,
) -> dict:
    """Execute a single local export; preserve evidence on failure.

    Never activates the exported model. The caller must separately validate
    compatibility, dictionary, independent test performance and rollback.
    """
    if not isinstance(timeout, int) or not 1 <= timeout <= MAX_EXPORT_SECONDS:
        raise TrainingError("Invalid export timeout")
    plan = build_paddle_export_plan(registry, model_id, training_python)
    root = Path(plan["output_dir"])
    root.mkdir(parents=True, exist_ok=False)
    log_path = root / "export.log"
    try:
        with log_path.open("wb") as log:
            result = subprocess.run(
                plan["args"], cwd=plan["cwd"], stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, shell=False,
                timeout=timeout, check=False,
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise TrainingError("Paddle export failed or timed out; inspect local export.log") from exc
    if result.returncode != 0:
        raise TrainingError("Paddle export returned a nonzero exit code; inspect local export.log")
    inference = Path(plan["inference_dir"])
    graph = next((inference / name for name in ("inference.json", "inference.pdmodel")
                  if (inference / name).is_file()), None)
    weights = inference / "inference.pdiparams"
    if graph is None or not weights.is_file() or graph.stat().st_size == 0 or weights.stat().st_size == 0:
        raise TrainingError("Paddle export did not produce a valid static graph and parameters")
    manifest = {
        "model_id": model_id, "run_id": plan["run_id"],
        "state": "paddle_exported_unverified",
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_checkpoint_sha256": plan["source_checkpoint_sha256"],
        "files": {
            graph.name: _sha256(graph),
            weights.name: _sha256(weights),
        },
        "note": "NOT verified for ONNX/RapidOCR; NOT activated; no quality claim.",
    }
    target = root / "manifest.json"
    tmp = root / "manifest.json.tmp"
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(target)
    return manifest
