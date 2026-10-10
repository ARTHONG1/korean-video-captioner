"""Frame-exact pause-edit rendering with seamless audio joints, plus render verification."""
from __future__ import annotations

import math
import re
import subprocess
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np

from .pause_signal import FRAME_H, FRAME_W, envelope_db

CROSSFADE_S = 0.024


def sample_at(frame: int, fps: Fraction, sample_rate: int) -> int:
    return int(round(frame * sample_rate / fps))


def open_pcm(path: Path) -> tuple[np.memmap, int, int]:
    """Memory-map a 16-bit PCM WAV written by FFmpeg."""
    with wave.open(str(path), "rb") as stream:
        channels, width, rate, count = stream.getnchannels(), stream.getsampwidth(), stream.getframerate(), stream.getnframes()
    if width != 2:
        raise ValueError("expected 16-bit PCM")
    size = Path(path).stat().st_size
    offset = size - count * channels * 2
    data = np.memmap(path, dtype="<i2", mode="r", offset=offset, shape=(count, channels))
    return data, rate, channels


def build_audio(src: np.ndarray, sample_rate: int, pieces: list[dict], fps: Fraction, output: Path,
                crossfade_s: float = CROSSFADE_S) -> int:
    """Join kept pieces; each joint is an equal-power crossfade that keeps total length exact.

    The crossfade reads a few milliseconds past each cut edge, which the plan
    guarantees are quiet, so no speech is doubled and no click is produced.
    Audio that ends before the video (common with AAC) is padded with silence
    so audio and video stay the same length; cuts never sit near the end.
    """
    half = max(1, int(round(sample_rate * crossfade_s / 2)))
    ramp = (np.arange(2 * half, dtype=np.float32) + 0.5) / (2 * half)
    fade_out = np.cos(ramp * math.pi / 2)[:, None]
    fade_in = np.sin(ramp * math.pi / 2)[:, None]
    written = 0
    channels = src.shape[1]
    with wave.open(str(output), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(sample_rate)

        def emit(block: np.ndarray) -> None:
            nonlocal written
            out.writeframes(np.ascontiguousarray(block, dtype="<i2").tobytes())
            written += block.shape[0]

        for index, piece in enumerate(pieces):
            start = sample_at(piece["src_start"], fps, sample_rate)
            target_end = sample_at(piece["src_end"], fps, sample_rate)
            end = min(target_end, src.shape[0])
            body_start = start + (half if index > 0 else 0)
            has_next = index + 1 < len(pieces)
            if has_next and target_end + half > src.shape[0]:
                raise ValueError("cut too close to the end of the audio")
            body_end = end - (half if has_next else 0)
            for chunk in range(body_start, body_end, sample_rate * 10):
                emit(src[chunk:min(body_end, chunk + sample_rate * 10)])
            if not has_next and target_end > end:
                emit(np.zeros((target_end - end, channels), dtype="<i2"))
            if has_next:
                nxt = sample_at(pieces[index + 1]["src_start"], fps, sample_rate)
                a = np.asarray(src[end - half:end + half], dtype=np.float32)
                b = np.asarray(src[nxt - half:nxt + half], dtype=np.float32)
                if a.shape[0] != 2 * half or b.shape[0] != 2 * half:
                    raise ValueError("crossfade window outside the audio")
                mixed = a * fade_out + b * fade_in
                emit(np.clip(np.round(mixed), -32768, 32767).astype("<i2"))
    return written


def select_expression(pieces: list[dict], fps: Fraction) -> str:
    """Keep source frames [src_start, src_end) by rounded absolute frame index (works with -copyts).

    The source is verified to be constant frame rate starting at 0, so round(t*fps) is the
    exact frame number; half-frame bounds keep the choice robust to timestamp jitter.
    """
    scale = f"t*{fps.numerator}/{fps.denominator}"
    terms = [f"gte({scale},{p['src_start'] - 0.5})*lt({scale},{p['src_end'] - 0.5})" for p in pieces]
    return "+".join(terms) if terms else "0"


def video_command(ffmpeg: Path, video: Path, audio: Path, script: Path, output: Path, fps: Fraction,
                  *, seek_s: float | None = None, length_s: float | None = None, crf: int = 16,
                  preset: str = "veryfast", progress: Path | None = None) -> list[str]:
    command = [str(ffmpeg), "-y", "-v", "error"]
    if progress:
        command += ["-progress", str(progress), "-nostats"]
    if seek_s is not None:
        command += ["-ss", f"{seek_s:.6f}", "-t", f"{length_s:.6f}", "-copyts"]
    command += ["-i", str(video), "-i", str(audio), "-/filter_complex", str(script),
                "-map", "[v]", "-map", "1:a", "-r", f"{fps.numerator}/{fps.denominator}",
                "-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", str(output)]
    return command


def write_filter_script(path: Path, pieces: list[dict], fps: Fraction) -> None:
    path.write_text(f"[0:v]select='{select_expression(pieces, fps)}',setpts=N/FRAME_RATE/TB[v]\n", encoding="utf-8")


# ---------------------------------------------------------------- verification

def probe(ffprobe: Path, path: Path) -> dict:
    result = subprocess.run(
        [str(ffprobe), "-v", "error", "-count_packets", "-show_entries",
         "stream=codec_type,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels,nb_read_packets,start_time:format=duration",
         "-of", "json", str(path)],
        check=True, capture_output=True, text=True, encoding="utf-8")
    import json
    return json.loads(result.stdout)


def extract_pcm(ffmpeg: Path, video: Path, wav: Path, sample_rate: int, channels: int) -> None:
    subprocess.run([str(ffmpeg), "-y", "-v", "error", "-i", str(video), "-vn", "-ac", str(channels), "-ar", str(sample_rate),
                    "-c:a", "pcm_s16le", str(wav)], check=True)


def gray_frame(ffmpeg: Path, video: Path, seconds: float) -> np.ndarray:
    result = subprocess.run(
        [str(ffmpeg), "-v", "error", "-ss", f"{seconds:.4f}", "-i", str(video), "-frames:v", "1",
         "-vf", f"scale={FRAME_W}:{FRAME_H}:flags=area,format=gray", "-f", "rawvideo", "-"],
        check=True, capture_output=True)
    data = np.frombuffer(result.stdout, dtype=np.uint8)
    if data.size != FRAME_W * FRAME_H:
        raise ValueError(f"could not read frame at {seconds:.3f}s")
    return data.reshape(FRAME_H, FRAME_W)


def verify_joints(out_env: np.ndarray, joints_s: list[float], threshold_db: float, hop_s: float = 0.01) -> list[dict]:
    """Every joint must sit in quiet audio in the rendered file (AAC adds a little noise)."""
    failures = []
    for joint in joints_s:
        a, b = max(0, int((joint - 0.03) / hop_s)), min(len(out_env), int((joint + 0.03) / hop_s) + 1)
        peak = float(np.max(out_env[a:b])) if b > a else float("inf")
        if peak > threshold_db + 4.0:
            failures.append({"joint_s": round(joint, 3), "peak_db": round(peak, 1)})
    return failures


def verify_sync(src_env: np.ndarray, out_env: np.ndarray, pieces: list[dict], fps: Fraction, floor_db: float,
                hop_s: float = 0.01) -> dict:
    """Compare loudness contours of each kept piece in source and output to catch drift or misplacement."""
    checked, worst, failures = 0, 0.0, []
    for piece in pieces:
        length = (piece["src_end"] - piece["src_start"]) / float(fps)
        if length < 1.0:
            continue
        s0 = int(round(piece["src_start"] / float(fps) / hop_s)) + 3
        o0 = int(round(piece["out_start"] / float(fps) / hop_s)) + 3
        n = int(length / hop_s) - 6
        if n <= 0 or o0 + n > len(out_env) or s0 + n > len(src_env):
            failures.append({"out_start_s": round(piece["out_start"] / float(fps), 3), "reason": "outside_audio"})
            continue
        a = np.maximum(src_env[s0:s0 + n], floor_db)
        b = np.maximum(out_env[o0:o0 + n], floor_db)
        if float(np.percentile(a, 90)) - floor_db < 10:
            continue
        diff = float(np.median(np.abs(a - b)))
        checked += 1
        worst = max(worst, diff)
        if diff > 3.0:
            failures.append({"out_start_s": round(piece["out_start"] / float(fps), 3), "median_db_diff": round(diff, 2)})
    return {"pieces_checked": checked, "worst_median_db_diff": round(worst, 2), "failures": failures}


def envelope_of(ffmpeg: Path, video: Path, work: Path, sample_rate: int, channels: int) -> np.ndarray:
    wav = work / (video.stem + ".verify.wav")
    extract_pcm(ffmpeg, video, wav, sample_rate, channels)
    try:
        data, rate, _ = open_pcm(wav)
        env = envelope_db(data, rate)
        del data
        return env
    finally:
        wav.unlink(missing_ok=True)


def parse_progress(path: Path) -> float | None:
    if not path.is_file():
        return None
    values = re.findall(r"out_time_us=(\d+)", path.read_text(encoding="utf-8", errors="ignore"))
    return int(values[-1]) / 1e6 if values else None
