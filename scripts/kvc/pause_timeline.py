"""Frame-exact source-to-output timeline for pause edits and subtitle remapping."""
from __future__ import annotations

import bisect
import re
from fractions import Fraction

from .models import Cue


def pieces_from_cuts(total_frames: int, cuts: list[tuple[int, int]]) -> list[dict]:
    pieces: list[dict] = []
    cursor = 0
    out = 0
    for start, end in sorted(cuts):
        if not cursor <= start < end <= total_frames:
            raise ValueError("cuts must be ordered, non-overlapping, and inside the video")
        if start > cursor:
            pieces.append({"src_start": cursor, "src_end": start, "out_start": out})
            out += start - cursor
        cursor = end
    if cursor < total_frames:
        pieces.append({"src_start": cursor, "src_end": total_frames, "out_start": out})
    return pieces


def output_frames(pieces: list[dict]) -> int:
    return sum(piece["src_end"] - piece["src_start"] for piece in pieces)


def window_pieces(pieces: list[dict], first: int, last: int) -> list[dict]:
    """Pieces clipped to source frames [first, last), renumbered from output frame 0."""
    result = []
    out = 0
    for piece in pieces:
        start, end = max(piece["src_start"], first), min(piece["src_end"], last)
        if end > start:
            result.append({"src_start": start, "src_end": end, "out_start": out})
            out += end - start
    return result


class Timeline:
    def __init__(self, pieces: list[dict], fps):
        self.pieces = pieces
        self.fps = Fraction(fps)
        self._starts = [piece["src_start"] for piece in pieces]

    def map_seconds(self, seconds: float) -> float:
        """Source seconds to output seconds; a time inside a removed span maps to its joint."""
        frame = seconds * float(self.fps)
        index = bisect.bisect_right(self._starts, frame) - 1
        if index < 0:
            return 0.0
        piece = self.pieces[index]
        offset = min(frame, piece["src_end"]) - piece["src_start"]
        return (piece["out_start"] + offset) / float(self.fps)

    def joints(self) -> list[float]:
        return [piece["out_start"] / float(self.fps) for piece in self.pieces[1:]]

    def to_json(self) -> dict:
        fps = float(self.fps)
        return {
            "schema_version": 1,
            "fps": str(self.fps.numerator) + "/" + str(self.fps.denominator),
            "output_frames": output_frames(self.pieces),
            "pieces": [
                {**piece, "source_start_s": round(piece["src_start"] / fps, 6), "source_end_s": round(piece["src_end"] / fps, 6),
                 "output_start_s": round(piece["out_start"] / fps, 6)}
                for piece in self.pieces
            ],
        }

    @classmethod
    def from_json(cls, value: dict) -> "Timeline":
        pieces = [{"src_start": p["src_start"], "src_end": p["src_end"], "out_start": p["out_start"]} for p in value["pieces"]]
        return cls(pieces, Fraction(value["fps"]))


def remap_cues(cues: list[Cue], timeline: Timeline) -> tuple[list[Cue], list[int]]:
    """Keep cue IDs; drop only cues whose span was (almost) entirely removed."""
    result: list[Cue] = []
    dropped: list[int] = []
    previous_end = 0
    for cue in cues:
        start = round(timeline.map_seconds(cue.start_ms / 1000) * 1000)
        end = round(timeline.map_seconds(cue.end_ms / 1000) * 1000)
        start = max(start, previous_end)
        if end <= start or (end - start < 200 and cue.end_ms - cue.start_ms >= 400):
            dropped.append(cue.id)
            continue
        result.append(Cue(cue.id, start, end, cue.text))
        previous_end = end
    return result, dropped


def strip_removed_words(text: str, removed: list[dict]) -> tuple[str, list[str]]:
    """Remove spoken fillers/repeats that were cut from the audio, only when they appear as whole words.

    A filler is removed once if it stands alone. A repeated phrase is removed once only when it
    still appears twice in a row. Anything else is left untouched and reported.
    """
    import re as _re

    unresolved = []
    for item in removed:
        phrase = _re.escape(item["text"].strip())
        if not phrase:
            continue
        if item["kind"] == "repetition":
            pattern = _re.compile(rf"(?<![\w가-힣])({phrase})[\s,…]+(?={phrase}(?![\w가-힣]))")
        else:
            pattern = _re.compile(rf"(?<![\w가-힣]){phrase}(?![\w가-힣])[\s,…]*")
        text, count = pattern.subn("", text, count=1)
        if not count:
            unresolved.append(item["id"])
    return _re.sub(r"\s{2,}", " ", text).strip(" ,"), unresolved


def remap_words(payload: dict, timeline: Timeline) -> tuple[dict, list[str]]:
    words = []
    dropped = []
    previous_end = 0
    for word in payload.get("words", []):
        start = round(timeline.map_seconds(word["start_ms"] / 1000) * 1000)
        end = round(timeline.map_seconds(word["end_ms"] / 1000) * 1000)
        start = max(start, previous_end)
        if end <= start:
            dropped.append(word.get("id", ""))
            continue
        words.append({**word, "start_ms": start, "end_ms": end})
        previous_end = end
    segments = []
    for segment in payload.get("segments", []):
        start = round(timeline.map_seconds(segment["start_ms"] / 1000) * 1000)
        end = round(timeline.map_seconds(segment["end_ms"] / 1000) * 1000)
        if end > start:
            segments.append({**segment, "start_ms": start, "end_ms": end,
                             "word_ids": [w for w in segment.get("word_ids", []) if w not in set(dropped)]})
    return {**payload, "words": words, "segments": segments}, dropped


_ASS_TIME = re.compile(r"^(Dialogue:\s*[^,]*,)(\d+:\d\d:\d\d\.\d\d),(\d+:\d\d:\d\d\.\d\d),")


def _ass_seconds(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _ass_stamp(seconds: float) -> str:
    centis = round(seconds * 100)
    hours, centis = divmod(centis, 360000)
    minutes, centis = divmod(centis, 6000)
    secs, centis = divmod(centis, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{centis:02d}"


def remap_ass(text: str, timeline: Timeline) -> tuple[str, int]:
    lines = []
    dropped = 0
    for line in text.splitlines():
        match = _ASS_TIME.match(line)
        if not match:
            lines.append(line)
            continue
        start = timeline.map_seconds(_ass_seconds(match.group(2)))
        end = timeline.map_seconds(_ass_seconds(match.group(3)))
        if end - start < 0.05:
            dropped += 1
            continue
        lines.append(match.group(1) + _ass_stamp(start) + "," + _ass_stamp(end) + "," + line[match.end():])
    return "\n".join(lines) + "\n", dropped
