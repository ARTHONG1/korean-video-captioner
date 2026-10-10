from __future__ import annotations

import argparse
import json
from pathlib import Path

from kvc.caption_context import write_correction_batches
from kvc.caption_models import WordEvidence
from kvc.models import Cue
from kvc.srt import parse_srt


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--srt", required=True)
    parser.add_argument("--words", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    cues = parse_srt(Path(args.srt).read_text(encoding="utf-8-sig"))
    payload = json.loads(Path(args.words).read_text(encoding="utf-8"))
    words = [WordEvidence(**item) for item in payload["words"]]
    write_correction_batches(Path(args.output), cues, words)


if __name__ == "__main__":
    main()
