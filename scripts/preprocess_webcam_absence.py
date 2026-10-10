from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvc.absence_driver import initialize_preprocess
from kvc.paths import RuntimePaths


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze webcam absence before captioning")
    parser.add_argument("--input", required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--ffprobe", default=None)
    args = parser.parse_args()
    runtime = RuntimePaths.discover()
    ffprobe = Path(args.ffprobe) if args.ffprobe else runtime.ffprobe
    result = initialize_preprocess(Path(args.input), Path(args.run), ffprobe)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
