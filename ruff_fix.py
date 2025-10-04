#!/usr/bin/env python3
"""
Run: ruff check --fix . && ruff format .
Works on Windows, macOS, Linux.
"""

from __future__ import annotations

import shutil
import subprocess
import sys


def run(cmd: list[str]) -> int:
    print("+", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def main() -> int:
    # Prefer the "ruff" exe if it’s on PATH; otherwise try `python -m ruff`
    ruff = shutil.which("ruff")
    if ruff:
        rc = run([ruff, "check", "--fix", "."])
        if rc != 0:
            return rc
        return run([ruff, "format", "."])
    else:
        # Fallback if only the module is available
        rc = run([sys.executable, "-m", "ruff", "check", "--fix", "."])
        if rc != 0:
            return rc
        return run([sys.executable, "-m", "ruff", "format", "."])


if __name__ == "__main__":
    raise SystemExit(main())
