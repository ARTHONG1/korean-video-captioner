import argparse
import json
from pathlib import Path

from kvc.brand_pack_io import install_brand_pack


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("archive")
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    installed = install_brand_pack(Path(args.archive), Path(args.root))
    print(json.dumps({"path": str(installed.path), "id": installed.pack.identifier}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
