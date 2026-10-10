"""Run one engine on one audio file inside the runtime venv and print JSON (used by setup.py selftest).

  asr_bench.py --wav speech.wav --engine faster-whisper|mlx [--profile balanced]
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import transcribe_faster_whisper as tfw  # noqa: E402
from kvc.asr_runner import COMMON_PARAMS, PROFILES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav", required=True)
    ap.add_argument("--engine", required=True, choices=["faster-whisper", "mlx"])
    ap.add_argument("--profile", default="balanced", choices=list(PROFILES))
    ap.add_argument("--threads", type=int, default=4)
    a = ap.parse_args()
    tfw.bootstrap_runtime()
    engine = tfw.engine_choice(a.engine)
    params = {**COMMON_PARAMS, **PROFILES[a.profile]}
    transcribe = tfw.transcriber_for(engine)
    started = time.time()
    rows = transcribe(Path(a.wav), params, a.threads, lambda _: None)
    seconds = time.time() - started
    words = sum(len(r["words"]) for r in rows)
    print(json.dumps({"engine": engine["name"], "seconds": round(seconds, 2), "text": " ".join(r["text"].strip() for r in rows),
                      "segments": len(rows), "words": words}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
