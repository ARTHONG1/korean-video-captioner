"""Resumable chunked Korean transcription with Whisper large-v3.

Engines:
  faster-whisper  CTranslate2 on CPU, int8 (every platform; the reference engine)
  mlx             mlx-whisper on the Apple Silicon GPU (macOS arm64 only)
--engine auto uses mlx only after setup.py selftest validated it on this Mac (runtime/engine.json), else faster-whisper.
"""
import argparse
import importlib.util as _ilu
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
# Load hostenv by file so the system Python (any 3.8+) never imports the rest of the kvc package.
_spec = _ilu.spec_from_file_location("kvc_hostenv", Path(__file__).resolve().parent / "kvc" / "hostenv.py")
hostenv = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(hostenv)

MLX_REPO = "mlx-community/whisper-large-v3-mlx"


def runtime_root() -> Path:
    return hostenv.runtime_root()


def runtime_python() -> Path:
    return hostenv.runtime_python()


def bootstrap_runtime() -> None:
    """Re-run this script inside the runtime venv (packages live only there)."""
    venv = runtime_root() / ".venv"
    if hostenv.in_venv(venv):
        return
    target = runtime_python()
    if not target.is_file():
        raise RuntimeError(f"Runtime Python not found: {target}. Run scripts/setup.py install (or set KVC_RUNTIME_ROOT).")
    result = subprocess.run([str(target), str(Path(sys.argv[0]).resolve()), *sys.argv[1:]])
    raise SystemExit(result.returncode)


def engine_choice(requested: str) -> dict:
    if requested == "faster-whisper":
        return {"name": "faster-whisper", "model": "large-v3", "device": "cpu", "compute_type": "int8"}
    validated = {}
    path = runtime_root() / "engine.json"
    if path.is_file():
        try:
            validated = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            validated = {}
    mlx_ok = hostenv.describe()["apple_silicon"] and importlib.util.find_spec("mlx_whisper") is not None
    if requested == "mlx" or (requested == "auto" and validated.get("engine") == "mlx" and validated.get("validated")):
        if not mlx_ok:
            if requested == "mlx":
                raise SystemExit("mlx engine needs macOS on Apple Silicon with mlx-whisper installed (setup.py install)")
        else:
            return {"name": "mlx", "model": MLX_REPO, "device": "apple-gpu", "compute_type": "float16"}
    return {"name": "faster-whisper", "model": "large-v3", "device": "cpu", "compute_type": "int8"}


def probe_duration_ms(video: Path, ffprobe: Path) -> int:
    result = subprocess.run(
        [str(ffprobe), '-v', 'error', '-show_entries', 'format=duration', '-of', 'default=noprint_wrappers=1:nokey=1', str(video)],
        check=True, capture_output=True, text=True, encoding='utf-8',
    )
    duration_ms = round(float(result.stdout.strip()) * 1000)
    if duration_ms <= 0:
        raise ValueError('video duration must be positive')
    return duration_ms


def make_extractor(video: Path, ffmpeg: Path):
    def extract(start_ms: int, end_ms: int, wav: Path) -> None:
        subprocess.run(
            [str(ffmpeg), '-y', '-v', 'error', '-ss', f'{start_ms / 1000:.3f}', '-i', str(video),
             '-t', f'{(end_ms - start_ms) / 1000:.3f}', '-vn', '-ac', '1', '-ar', '16000', str(wav)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
    return extract


def make_transcriber(model_holder: dict):
    """faster-whisper: load large-v3 once and stream segments so progress is reported during a chunk."""
    def transcribe(wav: Path, params: dict, cpu_threads: int, on_progress) -> list[dict]:
        from faster_whisper import WhisperModel

        if model_holder.get('threads') != cpu_threads:
            model_holder['model'] = WhisperModel('large-v3', device='cpu', compute_type='int8', cpu_threads=cpu_threads, num_workers=1)
            model_holder['threads'] = cpu_threads
        segments, _ = model_holder['model'].transcribe(str(wav), **params)
        rows = []
        for segment in segments:
            rows.append({
                'start_ms': round(float(segment.start) * 1000),
                'end_ms': round(float(segment.end) * 1000),
                'text': str(segment.text),
                'avg_logprob': float(segment.avg_logprob),
                'no_speech_prob': float(segment.no_speech_prob),
                'compression_ratio': float(segment.compression_ratio),
                'words': [
                    {'start_ms': round(float(w.start) * 1000), 'end_ms': round(float(w.end) * 1000),
                     'text': str(w.word), 'probability': float(w.probability)}
                    for w in (getattr(segment, 'words', None) or ()) if w.start is not None and w.end is not None
                ],
            })
            on_progress(rows[-1]['end_ms'])
        return rows
    return transcribe


def speech_regions(wav: Path, min_silence_ms: int = 500) -> list[tuple[int, int]] | None:
    """Silero VAD from faster-whisper (installed on every platform); None when unavailable."""
    try:
        from faster_whisper.audio import decode_audio
        from faster_whisper.vad import VadOptions, get_speech_timestamps
        audio = decode_audio(str(wav), sampling_rate=16000)
        stamps = get_speech_timestamps(audio, VadOptions(min_silence_duration_ms=min_silence_ms))
        return [(int(s["start"] / 16), int(s["end"] / 16)) for s in stamps]
    except Exception:
        return None


def make_mlx_transcriber(model_holder: dict):
    """mlx-whisper on the Apple Silicon GPU. Greedy decoding with temperature fallback (mlx-whisper has no beam
    search); segments outside VAD speech are dropped to match faster-whisper's vad_filter."""
    def transcribe(wav: Path, params: dict, cpu_threads: int, on_progress) -> list[dict]:
        import mlx_whisper

        regions = speech_regions(wav, params.get("vad_parameters", {}).get("min_silence_duration_ms", 500))
        if regions == []:
            return []
        result = mlx_whisper.transcribe(
            str(wav), path_or_hf_repo=MLX_REPO, language=params.get("language", "ko"), word_timestamps=True,
            condition_on_previous_text=params.get("condition_on_previous_text", True),
            temperature=tuple(params.get("temperature", [0.0, 0.2, 0.4])),
            hallucination_silence_threshold=params.get("hallucination_silence_threshold"), verbose=None,
        )
        rows = []
        for seg in result.get("segments", []):
            start, end = round(float(seg["start"]) * 1000), round(float(seg["end"]) * 1000)
            if regions is not None:
                middle = (start + end) / 2
                if not any(a - 300 <= middle <= b + 300 for a, b in regions):
                    continue
            rows.append({
                'start_ms': start, 'end_ms': end, 'text': str(seg.get("text", "")),
                'avg_logprob': float(seg.get("avg_logprob", 0.0)), 'no_speech_prob': float(seg.get("no_speech_prob", 0.0)),
                'compression_ratio': float(seg.get("compression_ratio", 0.0)),
                'words': [
                    {'start_ms': round(float(w["start"]) * 1000), 'end_ms': round(float(w["end"]) * 1000),
                     'text': str(w["word"]), 'probability': float(w.get("probability", 0.0))}
                    for w in seg.get("words", []) if w.get("start") is not None and w.get("end") is not None
                ],
            })
            on_progress(end)
        return rows
    return transcribe


def transcriber_for(engine: dict):
    return make_mlx_transcriber({}) if engine["name"] == "mlx" else make_transcriber({})


def main():
    bootstrap_runtime()
    p = argparse.ArgumentParser(description='Resumable chunked Whisper large-v3 Korean transcription')
    p.add_argument('video', nargs='?')
    p.add_argument('output', nargs='?', help='raw.srt path; words.json, asr-progress.json and asr-parts/ are written beside it')
    p.add_argument('--check-runtime', action='store_true')
    p.add_argument('--model-load-only', action='store_true')
    p.add_argument('--chunk-ms', type=int, default=300000)
    p.add_argument('--overlap-ms', type=int, default=2000)
    p.add_argument('--profile', choices=['auto', 'quality', 'balanced'], default='auto')
    p.add_argument('--engine', choices=['auto', 'faster-whisper', 'mlx'], default='auto')
    a = p.parse_args()
    engine = engine_choice(a.engine)
    if a.check_runtime:
        print(json.dumps({
            'python': str(Path(sys.executable)),
            'faster_whisper_importable': importlib.util.find_spec('faster_whisper') is not None,
            'mlx_whisper_importable': importlib.util.find_spec('mlx_whisper') is not None,
            'engine': engine,
        }))
        return
    if a.model_load_only:
        if engine['name'] == 'mlx':
            from huggingface_hub import snapshot_download
            snapshot_download(MLX_REPO)
        else:
            from faster_whisper import WhisperModel
            WhisperModel('large-v3', device='cpu', compute_type='int8')
        print(json.dumps(engine))
        return
    if not a.video or not a.output:
        p.error('video and output are required unless --check-runtime is used')

    from kvc.asr_runner import AsrLockError, AsrMemoryError, available_memory_bytes, run_transcription

    video = Path(a.video)
    ffmpeg, ffprobe = hostenv.tool('ffmpeg'), hostenv.tool('ffprobe')
    try:
        # word_timestamps=True and write_evidence are applied inside run_transcription.
        run_transcription(
            video, Path(a.output),
            duration_ms=probe_duration_ms(video, ffprobe),
            extract_audio=make_extractor(video, ffmpeg),
            transcribe_audio=transcriber_for(engine),
            requested_profile=a.profile,
            chunk_ms=a.chunk_ms,
            overlap_ms=a.overlap_ms,
            available=available_memory_bytes(),
            cores=os.cpu_count(),
            log=lambda line: print(line, flush=True),
            engine=engine,
        )
    except (AsrLockError, AsrMemoryError) as exc:
        print(f'ASR_BLOCKED {exc}', file=sys.stderr, flush=True)
        raise SystemExit(3)


if __name__ == '__main__':
    main()
