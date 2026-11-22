"""Optional CI integration test: actual PaddleOCR CPU train -> checkpoint -> resume.

Synthetic words are original fixtures. The test does not consume user images
or contact third-party OCR services at runtime.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFont

from localocr.training import TrainingManager, build_plan


WORDS = ["HELLO", "OCR", "PADDLE", "PYTHON", "IMAGE", "MODEL", "LETTER", "HELLO 2026"]


def create_dataset(root: Path) -> None:
    font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 48,
    )
    for split, count in (("train", 16), ("val", 4), ("test", 4)):
        directory = root / "rec" / split
        directory.mkdir(parents=True, exist_ok=True)
        lines = []
        for index in range(count):
            word = WORDS[(index + (3 if split == "test" else 0)) % len(WORDS)]
            picture = Image.new("RGB", (350, 70), "white")
            ImageDraw.Draw(picture).text((15 + index % 4, 3), word, font=font, fill="black")
            name = f"rec/{split}/sample_{index:03d}.png"
            picture.save(root / name)
            lines.append(f"{name}\t{word}\n")
        (root / f"rec_gt_{split}.txt").write_text("".join(lines), encoding="utf-8")


def run_training(manager: TrainingManager, plan: dict, *, timeout: int = 850) -> dict:
    status = manager.start(plan)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = manager.status()
        if status["status"] != "running":
            break
        time.sleep(3)
    else:
        manager.cancel()
        raise AssertionError("Timed out during PaddleOCR real training")
    if status["status"] != "completed":
        raise AssertionError(
            "PaddleOCR training exited unsuccessfully: "
            + json.dumps(status, ensure_ascii=False)[-6500:]
        )
    for suffix in (".pdparams", ".pdopt", ".states"):
        checkpoint = Path(status["output_dir"]) / ("latest" + suffix)
        assert checkpoint.is_file() and checkpoint.stat().st_size > 0, checkpoint
    print("PaddleOCR completed and saved all checkpoint types:", status["id"])
    return status


def main() -> int:
    repo = Path(sys.argv[1]).resolve()
    pretrain = Path(sys.argv[2]).resolve()
    work = Path(sys.argv[3]).resolve()
    assert (repo / "tools" / "train.py").is_file(), repo
    assert pretrain.is_file() and pretrain.stat().st_size > 1_000_000, pretrain
    data = work / "data"
    create_dataset(data)
    root = work / "training"
    manager = TrainingManager(root)
    first = build_plan(str(repo), str(data), str(pretrain), epochs=1, batch_size=2,
                       use_gpu=False, output_dir=root / "runs" / uuid4().hex)
    print("Beginning stage 1 real PaddleOCR model update")
    one = run_training(manager, first)
    second = build_plan(
        str(repo), str(data), str(pretrain),
        epochs=2, batch_size=2, use_gpu=False,
        resume_run_id=one["id"], resume_root=root / "runs",
        output_dir=root / "runs" / uuid4().hex,
    )
    assert "Global.checkpoints=" in " ".join(second["args"])
    assert second["resume_from"]["run_id"] == one["id"]
    print("Beginning stage 2 checkpoint resumption")
    two = run_training(manager, second)
    assert two["resume_from"]["run_id"] == one["id"]
    print("REAL_PADDLE_TRAIN_RESUME_OK")
    # Training is validated; model quality requires an independent benchmark.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
