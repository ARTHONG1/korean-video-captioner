from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kvc.absence_models import Action, TimelineSegment
from kvc.absence_render import build_filter_graph


def load_segments(path: Path) -> list[TimelineSegment]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [TimelineSegment(float(x["source_start"]), float(x["source_end"]), Action(x["action"]), float(x["speed"])) for x in data]


def render(input_path: Path, output_path: Path, segments: list[TimelineSegment], ffmpeg: Path, has_audio: bool = True) -> None:
    graph = build_filter_graph(segments, has_audio=has_audio)
    if not graph:
        raise ValueError("timeline contains no media")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_path.with_suffix(output_path.suffix + ".tmp.mp4")
    command = [str(ffmpeg), "-y", "-i", str(input_path), "-filter_complex", graph, "-map", "[vout]"]
    if has_audio:
        command += ["-map", "[aout]"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-movflags", "+faststart", str(temporary)]
    subprocess.run(command, check=True)
    temporary.replace(output_path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a reviewed webcam absence timeline")
    parser.add_argument("--input", required=True)
    parser.add_argument("--timeline", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--ffmpeg", required=True)
    parser.add_argument("--no-audio", action="store_true")
    args = parser.parse_args()
    render(Path(args.input), Path(args.output), load_segments(Path(args.timeline)), Path(args.ffmpeg), not args.no_audio)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
