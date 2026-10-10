from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


PINNED = ("numpy==2.2.6", "opencv-python-headless==4.14.0.94")


def bootstrap(target: Path) -> None:
    if not target.exists():
        subprocess.run([sys.executable, "-m", "venv", str(target)], check=True)
    python = target / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([str(python), "-m", "pip", "install", "--disable-pip-version-check", *PINNED], check=True)
    subprocess.run([str(python), "-c", "import cv2, numpy; print(cv2.__version__, numpy.__version__)"], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the isolated local vision runtime")
    parser.add_argument("--target", required=True)
    args = parser.parse_args()
    bootstrap(Path(args.target))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
