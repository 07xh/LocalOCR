"""Validate the actual PyInstaller Windows bundle, including real ONNX OCR."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from PIL import Image, ImageDraw, ImageFont


def main() -> int:
    exe = Path(sys.argv[1]).resolve()
    root = exe.parent
    assert exe.is_file(), exe
    # Run the frozen executable from a different working directory.
    environment = dict(os.environ)
    environment["LOCALOCR_CONFIG_DIR"] = str(Path(os.environ["RUNNER_TEMP"]) / "LocalOCR-CI")
    cwd = Path(os.environ["RUNNER_TEMP"])
    models = list(root.rglob("*.onnx"))
    assert models, "No bundled RapidOCR ONNX models found"
    assert any("rec" in file.name.lower() for file in models), "Missing recognition model"
    env_result = subprocess.run(
        [str(exe), "engines"], cwd=cwd, env=environment,
        capture_output=True, text=True, timeout=60, check=False,
    )
    if env_result.returncode:
        raise AssertionError("Frozen CLI failed:\n" +
                             (env_result.stdout + env_result.stderr)[-7000:])
    engines = json.loads(env_result.stdout.strip())
    assert engines["rapidocr"] is True, engines

    image = Image.new("RGB", (900, 180), "white")
    font_path = Path(os.environ["WINDIR"]) / "Fonts" / "arial.ttf"
    font = ImageFont.truetype(str(font_path), 78)
    ImageDraw.Draw(image).text((30, 30), "HELLO 2026", font=font, fill="black")
    input_image = cwd / "localocr-bundle-smoke.png"
    image.save(input_image)
    result = subprocess.run(
        [str(exe), "recognize", str(input_image), "--engine", "rapidocr"],
        cwd=cwd, env=environment, capture_output=True, text=True,
        timeout=180, check=True,
    )
    output = json.loads(result.stdout)
    compact = output["text"].upper().replace(" ", "")
    assert "HELLO" in compact and "2026" in compact, output
    print("Frozen Windows RapidOCR: recognition success")

    proc = subprocess.Popen(
        [str(exe), "studio", "--no-browser", "--port", "18769"],
        cwd=cwd, env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        for attempt in range(45):
            if proc.poll() is not None:
                error_output = proc.stderr.read().decode("utf-8", "replace") if proc.stderr else ""
                raise AssertionError("Frozen server exited with " + str(proc.returncode) +
                                     "\\n" + error_output[-6000:])
            try:
                with urlopen("http://127.0.0.1:18769/health", timeout=2) as response:
                    assert json.load(response)["status"] == "ok"
                break
            except (URLError, TimeoutError):
                time.sleep(1)
        else:
            raise AssertionError("Frozen Studio did not start")
        with urlopen("http://127.0.0.1:18769/studio", timeout=5) as response:
            assert "LocalOCR" in response.read().decode("utf-8")
        with urlopen("http://127.0.0.1:18769/assets/studio.js", timeout=5) as response:
            assert b"trainingConfig" in response.read()
        try:
            urlopen(Request("http://127.0.0.1:18769/v1/engines"), timeout=5)
        except Exception as error:
            assert getattr(error, "code", None) == 401, error
        else:
            raise AssertionError("Unauthenticated API was accepted")
        print("Frozen Windows Studio: HTTP, JS assets, and API auth success")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
