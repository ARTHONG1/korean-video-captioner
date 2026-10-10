"""Resumable, chunked Faster-Whisper transcription.

The runner is independent of Faster-Whisper so it can be tested with fakes.
Each finished chunk is saved under asr-parts/ and reused on the next run,
asr-progress.json reports processed audio, and asr.lock prevents a
second transcription of the same run.
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable

from .asr_evidence import write_evidence
from .caption_models import SegmentEvidence, WordEvidence
from .chunking import plan_chunks
from .models import Cue
from .srt import write_srt

PART_SCHEMA_VERSION = 1
PROFILES = {
    "quality": {"beam_size": 5, "best_of": 5, "temperature": [0.0, 0.2, 0.4]},
    "balanced": {"beam_size": 3, "best_of": 3, "temperature": [0.0, 0.2]},
}
COMMON_PARAMS = {
    "language": "ko",
    "vad_filter": True,
    "vad_parameters": {"min_silence_duration_ms": 500},
    "word_timestamps": True,
    "condition_on_previous_text": True,
    "hallucination_silence_threshold": 2.0,
}
QUALITY_MIN_AVAILABLE_BYTES = 5 * 1024**3
MIN_AVAILABLE_BYTES = int(1.5 * 1024**3)
PROGRESS_WRITE_INTERVAL_S = 10.0

ExtractAudio = Callable[[int, int, Path], None]
# (wav, params, cpu_threads, on_progress(relative_end_ms)) -> relative segment dicts
TranscribeAudio = Callable[[Path, dict, int, Callable[[int], None]], list[dict]]


class AsrLockError(RuntimeError):
    """Another live process is already transcribing this run."""


class AsrMemoryError(RuntimeError):
    """Too little free memory to start a transcription safely."""


def _now_iso(timestamp: float | None = None) -> str:
    moment = datetime.fromtimestamp(timestamp if timestamp is not None else time.time(), UTC)
    return moment.isoformat(timespec="seconds").replace("+00:00", "Z")


def _write_json(path: Path, value: dict) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, path)


def available_memory_bytes() -> int | None:
    """Free physical memory, or None when the platform does not report it (see kvc.hostenv)."""
    from .hostenv import available_memory_bytes as _available
    return _available()


def select_profile(requested: str, available: int | None) -> str:
    if requested in PROFILES:
        return requested
    if requested != "auto":
        raise ValueError(f"unknown ASR profile: {requested}")
    if available is None or available >= QUALITY_MIN_AVAILABLE_BYTES:
        return "quality"
    return "balanced"


def cpu_threads_for(available: int | None, cores: int | None) -> int:
    cores = cores or 4
    if available is not None and available < QUALITY_MIN_AVAILABLE_BYTES:
        return max(1, min(4, cores))
    return max(1, min(8, cores))


def pid_alive(pid: int) -> bool:
    """Check a PID without signalling it (os.kill terminates processes on Windows)."""
    from .hostenv import pid_alive as _alive
    return _alive(pid)


@contextmanager
def run_lock(run: Path, is_alive: Callable[[int], bool] = pid_alive):
    lock = Path(run) / "asr.lock"
    payload = json.dumps({"pid": os.getpid(), "started_at": _now_iso()})
    for _ in range(2):
        try:
            descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                owner = int(json.loads(lock.read_text(encoding="utf-8")).get("pid", 0))
            except Exception:
                owner = 0
            if owner and owner != os.getpid() and is_alive(owner):
                raise AsrLockError(f"transcription already running for this run (pid {owner}); do not start another")
            lock.unlink(missing_ok=True)  # stale lock from a dead process
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(payload)
        break
    else:
        raise AsrLockError(f"could not acquire {lock}")
    try:
        yield lock
    finally:
        lock.unlink(missing_ok=True)


def source_fingerprint(video: Path) -> dict:
    stat = Path(video).stat()
    return {"path": str(Path(video).resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def owned_bounds(chunks: list[tuple[int, int]], index: int, overlap_ms: int) -> tuple[float, float]:
    """Each chunk owns segments whose midpoint lies before the middle of the next overlap."""
    low = chunks[index][0] + overlap_ms / 2 if index > 0 else float("-inf")
    high = chunks[index][1] - overlap_ms / 2 if index < len(chunks) - 1 else float("inf")
    return low, high


def _absolute(segment: dict, offset_ms: int) -> dict:
    words = [
        {
            "start_ms": offset_ms + int(word["start_ms"]),
            "end_ms": offset_ms + int(word["end_ms"]),
            "text": str(word["text"]).strip(),
            "probability": float(word.get("probability", 0.0)),
        }
        for word in segment.get("words", [])
        if str(word.get("text", "")).strip()
    ]
    return {
        "start_ms": offset_ms + int(segment["start_ms"]),
        "end_ms": offset_ms + int(segment["end_ms"]),
        "text": str(segment["text"]).strip(),
        "avg_logprob": float(segment.get("avg_logprob", 0.0)),
        "no_speech_prob": float(segment.get("no_speech_prob", 0.0)),
        "compression_ratio": float(segment.get("compression_ratio", 0.0)),
        "words": words,
    }


def _load_part(path: Path, key: dict, start_ms: int, end_ms: int) -> dict | None:
    if not path.is_file():
        return None
    try:
        part = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if (
        part.get("schema_version") != PART_SCHEMA_VERSION
        or part.get("key") != key
        or part.get("start_ms") != start_ms
        or part.get("end_ms") != end_ms
        or not isinstance(part.get("segments"), list)
    ):
        return None
    return part


class _Progress:
    def __init__(self, path: Path, base: dict, clock: Callable[[], float]):
        self.path = path
        self.data = dict(base)
        self.clock = clock
        self._last = float("-inf")

    def update(self, force: bool = False, **values) -> None:
        self.data.update(values)
        now = self.clock()
        if not force and now - self._last < PROGRESS_WRITE_INTERVAL_S:
            return
        duration = max(1, int(self.data.get("duration_ms", 1)))
        self.data["percent"] = round(100 * min(duration, int(self.data.get("processed_ms", 0))) / duration, 1)
        self.data["updated_at"] = _now_iso(now)
        _write_json(self.path, self.data)
        self._last = now


def _monotonic(items: list[dict]) -> list[dict]:
    """Keep start >= previous end and end > start, which the SRT parser requires."""
    ordered = sorted(items, key=lambda item: (item["start_ms"], item["end_ms"]))
    result: list[dict] = []
    for item in ordered:
        item = dict(item)
        if result and item["start_ms"] < result[-1]["end_ms"]:
            previous = result[-1]
            previous["end_ms"] = max(previous["start_ms"] + 1, item["start_ms"])
            item["start_ms"] = max(item["start_ms"], previous["end_ms"])
        if item["end_ms"] <= item["start_ms"]:
            item["end_ms"] = item["start_ms"] + 1
        result.append(item)
    return result


def assemble_outputs(parts: list[dict], raw_srt: Path, profile: dict) -> dict:
    segments = _monotonic([segment for part in parts for segment in part["segments"] if segment["text"]])
    cues: list[Cue] = []
    evidence: list[SegmentEvidence] = []
    all_words: list[dict] = []
    for index, segment in enumerate(segments, 1):
        cues.append(Cue(index, segment["start_ms"], segment["end_ms"], segment["text"]))
        for word in segment["words"]:
            all_words.append({**word, "segment_id": index, "chunk": segment.get("chunk", "")})
        evidence.append(
            SegmentEvidence(
                index, segment["start_ms"], segment["end_ms"], segment["text"],
                segment["avg_logprob"], segment["no_speech_prob"], segment["compression_ratio"], (),
            )
        )
    words: list[WordEvidence] = []
    word_ids: dict[int, list[str]] = {}
    for number, word in enumerate(_monotonic(all_words), 1):
        word_id = f"w-{number:06d}"
        words.append(
            WordEvidence(word_id, word["start_ms"], word["end_ms"], word["text"],
                         min(1.0, max(0.0, word["probability"])), word["chunk"], word["segment_id"])
        )
        word_ids.setdefault(word["segment_id"], []).append(word_id)
    evidence = [
        SegmentEvidence(item.id, item.start_ms, item.end_ms, item.text, item.avg_logprob,
                        item.no_speech_prob, item.compression_ratio, tuple(word_ids.get(item.id, ())))
        for item in evidence
    ]
    raw_srt = Path(raw_srt)
    raw_srt.write_text(write_srt(cues), encoding="utf-8-sig")
    write_evidence(raw_srt.with_name("words.json"), words, evidence, profile)
    _write_json(raw_srt.with_name("asr-profile.json"), profile)
    return {"cue_count": len(cues), "word_count": len(words)}


def run_transcription(
    video: Path,
    raw_srt: Path,
    *,
    duration_ms: int,
    extract_audio: ExtractAudio,
    transcribe_audio: TranscribeAudio,
    requested_profile: str = "auto",
    chunk_ms: int = 300_000,
    overlap_ms: int = 2_000,
    available: int | None = None,
    cores: int | None = None,
    clock: Callable[[], float] = time.time,
    is_alive: Callable[[int], bool] = pid_alive,
    log: Callable[[str], None] = print,
    engine: dict | None = None,
) -> dict:
    raw_srt = Path(raw_srt)
    run = raw_srt.parent
    run.mkdir(parents=True, exist_ok=True)
    if available is not None and available < MIN_AVAILABLE_BYTES:
        raise AsrMemoryError(
            f"only {available / 1024**3:.1f} GB free; close other apps and rerun (need {MIN_AVAILABLE_BYTES / 1024**3:.1f} GB)"
        )
    chunks = plan_chunks(duration_ms, chunk_ms, overlap_ms)
    profile_name = select_profile(requested_profile, available)
    params = {**COMMON_PARAMS, **PROFILES[profile_name]}
    threads = cpu_threads_for(available, cores)
    key = {
        "source": source_fingerprint(video), "profile": profile_name, "params": params,
        "chunk_ms": chunk_ms, "overlap_ms": overlap_ms,
    }
    engine = engine or {"name": "faster-whisper", "model": "large-v3", "device": "cpu", "compute_type": "int8"}
    if engine.get("name") != "faster-whisper":
        key["engine"] = engine.get("name")  # older parts (no engine key) stay valid for faster-whisper
    parts_dir = run / "asr-parts"
    parts_dir.mkdir(exist_ok=True)
    with run_lock(run, is_alive):
        progress = _Progress(run / "asr-progress.json", {
            "schema_version": 1, "state": "running", "pid": os.getpid(), "profile": profile_name,
            "engine": engine.get("name"), "cpu_threads": threads, "memory_available_bytes": available, "duration_ms": duration_ms,
            "chunks_total": len(chunks), "chunks_done": 0, "chunks_reused": 0, "current_chunk": None,
            "processed_ms": 0, "started_at": _now_iso(clock()),
        }, clock)
        progress.update(force=True)
        try:
            parts: list[dict] = []
            reused = 0
            for index, (start_ms, end_ms) in enumerate(chunks):
                path = parts_dir / f"chunk-{index:04d}.json"
                part = _load_part(path, key, start_ms, end_ms)
                if part is None:
                    progress.update(force=True, current_chunk=index, processed_ms=start_ms)
                    wav = parts_dir / f"chunk-{index:04d}.wav"
                    extract_audio(start_ms, end_ms, wav)
                    try:
                        relative = transcribe_audio(
                            wav, params, threads,
                            lambda end_rel, s=start_ms, e=end_ms: progress.update(processed_ms=min(e, s + int(end_rel))),
                        )
                    finally:
                        wav.unlink(missing_ok=True)
                    low, high = owned_bounds(chunks, index, overlap_ms)
                    owned = []
                    for segment in relative:
                        absolute = _absolute(segment, start_ms)
                        middle = (absolute["start_ms"] + absolute["end_ms"]) / 2
                        if absolute["text"] and low <= middle < high:
                            owned.append({**absolute, "chunk": f"chunk-{index:04d}"})
                    part = {"schema_version": PART_SCHEMA_VERSION, "key": key, "start_ms": start_ms,
                            "end_ms": end_ms, "segments": owned}
                    _write_json(path, part)
                    log(f"CHUNK_DONE {index + 1}/{len(chunks)} {start_ms}-{end_ms} segments={len(owned)}")
                else:
                    reused += 1
                    log(f"CHUNK_REUSED {index + 1}/{len(chunks)} {start_ms}-{end_ms}")
                parts.append(part)
                progress.update(force=True, chunks_done=index + 1, chunks_reused=reused, processed_ms=end_ms)
            profile = {
                "model": engine.get("model", "large-v3"), "engine": engine.get("name"), "device": engine.get("device", "cpu"),
                "compute_type": engine.get("compute_type", "int8"), "profile": profile_name,
                **params, "cpu_threads": threads, "chunk_ms": chunk_ms, "overlap_ms": overlap_ms,
                "duration_ms": duration_ms, "chunks": len(chunks), "memory_available_bytes": available,
            }
            summary = assemble_outputs(parts, raw_srt, profile)
            progress.update(force=True, state="done", current_chunk=None, processed_ms=duration_ms, **summary)
            log("RAW_DONE")
            return summary
        except BaseException as exc:
            progress.update(force=True, state="failed", error=f"{type(exc).__name__}: {exc}")
            raise


def transcribe_span(
    start_ms: int, end_ms: int, output: Path, *, extract_audio: ExtractAudio,
    transcribe_audio: TranscribeAudio, requested_profile: str = "quality",
    available: int | None = None, cores: int | None = None,
) -> dict:
    """Re-transcribe one retry span and save absolute-time segments for review."""
    if end_ms <= start_ms or start_ms < 0:
        raise ValueError("invalid span")
    profile_name = select_profile(requested_profile, available)
    params = {**COMMON_PARAMS, **PROFILES[profile_name]}
    output = Path(output)
    wav = output.with_suffix(".wav")
    extract_audio(start_ms, end_ms, wav)
    try:
        relative = transcribe_audio(wav, params, cpu_threads_for(available, cores), lambda _: None)
    finally:
        wav.unlink(missing_ok=True)
    result = {"schema_version": 1, "start_ms": start_ms, "end_ms": end_ms, "profile": profile_name,
              "segments": [_absolute(segment, start_ms) for segment in relative if str(segment.get("text", "")).strip()]}
    _write_json(output, result)
    return result
