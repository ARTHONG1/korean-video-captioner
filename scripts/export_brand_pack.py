import argparse
from pathlib import Path

from kvc.brand_pack_io import export_brand_pack


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source")
    parser.add_argument("destination")
    args = parser.parse_args()
    print(export_brand_pack(Path(args.source), Path(args.destination)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
