import argparse
import json
from pathlib import Path

from kvc.brand_pack import load_brand_pack
from kvc.youtube_verify import verify_youtube_attempt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("attempt")
    parser.add_argument("--brand-pack", required=True)
    args = parser.parse_args()
    pack = load_brand_pack(Path(args.brand_pack))
    result = verify_youtube_attempt(Path(args.attempt), {"book": pack.profile.book.sha256, "character": pack.profile.character.sha256})
    (Path(args.attempt) / "verify-youtube.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
