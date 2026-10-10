import argparse
import json
from pathlib import Path

from kvc.ai_thumbnail_pipeline import finalize_ai_thumbnail, prepare_ai_thumbnail


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare")
    prepare.add_argument("--attempt", required=True)
    prepare.add_argument("--proposal", required=True)
    prepare.add_argument("--brand-pack")
    prepare.add_argument("--scene-image", help="optional frame from the video the user wants in the thumbnail (Image 3)")
    prepare.add_argument("--scene-description")
    finalize = commands.add_parser("finalize")
    finalize.add_argument("--attempt", required=True)
    finalize.add_argument("--review", required=True)
    finalize.add_argument("--brand-pack")
    args = parser.parse_args()
    pack = Path(args.brand_pack) if args.brand_pack else None
    if args.command == "prepare":
        scene = Path(args.scene_image) if args.scene_image else None
        print(json.dumps({"request": str(prepare_ai_thumbnail(Path(args.attempt), Path(args.proposal), pack, scene, args.scene_description))},
                         ensure_ascii=False))
        return 0
    result = finalize_ai_thumbnail(Path(args.attempt), Path(args.review), pack)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("overall") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
