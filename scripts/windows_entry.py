"""PyInstaller entrypoint: double-click opens the local Studio by default."""
from __future__ import annotations

import sys

from localocr.cli import main

if __name__ == "__main__":
    if len(sys.argv) == 1:
        sys.argv.append("studio")
    raise SystemExit(main())
