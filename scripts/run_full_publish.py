import argparse
import json
from pathlib import Path

from kvc.full_publish_driver import run_until_tool_action
from kvc.full_publish_state import initialize_workflow, record_transition


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--input", required=True)
    init.add_argument("--run", required=True)
    init.add_argument("--mode", default="full-publish")
    init.add_argument("--webcam-preprocess", action="store_true", help="opt in to webcam-absence speed/cut preprocessing")
    init.add_argument("--no-compact", action="store_true", help="user asked for no cut/speed change on this video")
    init.add_argument("--compact", action="store_true", help="force compact edit on even if the profile disables it")
    init.add_argument("--no-intro", action="store_true", help="user asked for no promo intro on this video")
    init.add_argument("--intro", action="store_true", help="force the promo intro on")
    action = commands.add_parser("next")
    action.add_argument("--workflow", required=True)
    record = commands.add_parser("record")
    record.add_argument("--workflow", required=True)
    record.add_argument("--action", required=True)
    record.add_argument("--artifacts", required=True, help="JSON object of artifact names to hashes/paths/status")
    args = parser.parse_args()
    if args.command == "init":
        compact = False if args.no_compact else (True if args.compact else None)
        intro = False if args.no_intro else (True if args.intro else None)
        path = initialize_workflow(Path(args.input), Path(args.run), args.mode, args.webcam_preprocess, compact, intro)
        print(json.dumps({"workflow": str(path)}, ensure_ascii=False))
    elif args.command == "record":
        value = record_transition(Path(args.workflow), args.action, json.loads(args.artifacts))
        print(json.dumps({"phase": value["phase"], "post_stages": value.get("post_stages", {})}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps(run_until_tool_action(Path(args.workflow)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
