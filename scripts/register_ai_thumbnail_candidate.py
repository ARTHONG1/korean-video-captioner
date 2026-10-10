import argparse
import json
from pathlib import Path

from kvc.ai_thumbnail_candidates import register_candidate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--attempt", required=True)
    parser.add_argument("--generated", required=True)
    parser.add_argument("--variant", required=True)
    args = parser.parse_args()
    print(json.dumps(register_candidate(Path(args.attempt), Path(args.generated), args.variant), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
