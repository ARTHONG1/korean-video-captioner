import argparse
import json
from pathlib import Path

from kvc.youtube_orchestrator import finalize_attempt, prepare_attempt


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--run", required=True)
    prepare.add_argument("--brand-pack")
    prepare.add_argument("--final-video")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--attempt", required=True)
    finalize.add_argument("--brand-pack")
    finalize.add_argument("--proposal", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        attempt = prepare_attempt(Path(args.run), Path(args.brand_pack) if args.brand_pack else None, Path(args.final_video) if args.final_video else None)
        print(json.dumps({"attempt": str(attempt), "proposal": str(attempt / "metadata-proposal.json")}, ensure_ascii=False))
        return 0
    verify = finalize_attempt(Path(args.attempt), Path(args.proposal), Path(args.brand_pack) if args.brand_pack else None)
    print(json.dumps(verify, ensure_ascii=False))
    return 0 if verify["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
