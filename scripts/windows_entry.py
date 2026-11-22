"""PyInstaller entrypoint: double-click opens the local Studio by default."""
from __future__ import annotations

import sys

# A static import forces PyInstaller to analyze the complete FastAPI/SQLite
# dependency graph; data collection alone does not compile nested imports.
from localocr.api import app as _bundled_app
from localocr.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("studio")
    raise SystemExit(main())
