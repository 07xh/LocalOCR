"""Persistent API key stored outside the source tree (never tracked in Git)."""
import json
import os
import secrets
from pathlib import Path


def config_dir() -> Path:
    base = os.environ.get("LOCALOCR_CONFIG_DIR")
    if base:
        return Path(base).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "LocalOCR"
    return Path.home() / ".config" / "localocr"


def api_key() -> str:
    env = os.environ.get("LOCALOCR_API_KEY")
    if env:
        return env
    directory = config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "auth.json"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data.get("api_key"), str) or not data["api_key"]:
            raise ValueError("Invalid API key configuration")
        return data["api_key"]
    token = secrets.token_urlsafe(32)
    # Restrict permissions on POSIX and avoid accidentally committing keys.
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    try:
        fd = os.open(path, flags, 0o600)
    except FileExistsError:
        return json.loads(path.read_text(encoding="utf-8"))["api_key"]
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"api_key": token}, f)
    return token
