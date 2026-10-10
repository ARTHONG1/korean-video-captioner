"""Prepend a rendered promo intro to the main video without re-encoding the main video.

  intro_join.py --intro INTRO.mp4 --main compact.mp4 --out final-with-intro-compact.mp4
                [--main-audio compact-audio.wav] [--srt publication-compact.srt] [--fade 0.45]
The intro is conformed to the main video's size, frame rate, color and encoder settings, then both are
joined with stream copy. If the H.264 parameter sets still differ, the whole file is re-encoded instead.
Writes OUT, OUT.timeline.json (source -> final time map), OUT.publication.srt, and OUT.join-verify.json.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kvc.compact_timeline import load_timeline, timeline_path  # noqa: E402
from kvc.media_tools import SR, VIDEO_TAIL, X264, count_frames, extradata, fps_expr, log, probe, samples_at, sh, stream_duration  # noqa: E402
from kvc.paths import RuntimePaths  # noqa: E402
from kvc.srt import _stamp, parse_srt  # noqa: E402

P = RuntimePaths.discover()
FF, FP = P.ffmpeg, P.ffprobe


def wav_read(path: Path) -> np.ndarray:
    w = wave.open(str(path), "rb")
    x = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, w.getnchannels())
    w.close()
    return x


def decode_wav(src: Path, dst: Path, extra_af: str = "") -> None:
    af = "aresample=48000:async=1:min_hard_comp=0.001:first_pts=0" + ("," + extra_af if extra_af else "")
    sh([FF, "-y", "-v", "error", "-i", src, "-vn", "-af", af, "-ac", "2", "-ar", str(SR), "-c:a", "pcm_s16le", dst])


def fit(x: np.ndarray, n: int) -> np.ndarray:
    z = np.zeros((n, 2), np.int16)
    z[:min(n, len(x))] = x[:n]
    return z


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--intro", required=True)
    ap.add_argument("--main", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--main-audio")
    ap.add_argument("--srt")
    ap.add_argument("--fade", type=float, default=0.45)
    ap.add_argument("--intro-gain-db", type=float, default=0.0, help="optional intro loudness change; the report flags gaps over 10 dB")
    a = ap.parse_args()
    intro, main_v, out = Path(a.intro).resolve(), Path(a.main).resolve(), Path(a.out).resolve()
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    work = out.parent / (out.stem + ".join-work")
    work.mkdir(exist_ok=True)
    mi, ii = probe(FP, main_v), probe(FP, intro)
    fps, W, H = mi["fps"], mi["width"], mi["height"]
    n_main = count_frames(FP, main_v)
    n_intro = int(round(Fraction(ii["duration"]).limit_denominator(1000) * fps))
    vdur = stream_duration(FP, intro, "v")
    if vdur:
        n_intro = int(round(Fraction(vdur).limit_denominator(100000) * fps))
    fade_st = float(n_intro / fps) - a.fade
    rng = "scale=in_range=full:out_range=tv," if (ii["pix_fmt"] or "").startswith("yuvj") else ""
    vf = (f"{rng}scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={fps_expr(fps)},"
          f"fade=t=out:st={fade_st:.3f}:d={a.fade},{VIDEO_TAIL}")
    intro_v = work / "intro_conformed.mp4"
    sh([FF, "-y", "-v", "error", "-threads", "4", "-i", intro, "-an", "-vf", vf, "-frames:v", str(n_intro)] + X264 + [intro_v])
    n_intro = count_frames(FP, intro_v)
    same_params = extradata(FP, intro_v) == extradata(FP, main_v) and extradata(FP, main_v) is not None
    log("intro frames", n_intro, "main frames", n_main, "parameter sets match" if same_params else "parameter sets differ -> re-encode")
    # audio: intro padded/trimmed to its video length with a fade, then the main audio sample-exact
    total = samples_at(n_intro + n_main, fps)
    main_wav = Path(a.main_audio) if a.main_audio else work / "main.wav"
    if not a.main_audio:
        decode_wav(main_v, main_wav)
    m = wav_read(main_wav)
    n_m = samples_at(n_main, fps)
    n_i = total - n_m
    if ii["has_audio"]:
        gain = f"volume={a.intro_gain_db}dB," if a.intro_gain_db else ""
        decode_wav(intro, work / "intro.wav", f"{gain}afade=t=out:st={fade_st:.3f}:d={a.fade}")
        x_i = fit(wav_read(work / "intro.wav"), n_i)
    else:
        x_i = np.zeros((n_i, 2), np.int16)
    final_wav = work / "final.wav"
    w = wave.open(str(final_wav), "wb")
    w.setnchannels(2)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes(x_i.tobytes())
    w.writeframes(fit(m, n_m).tobytes())
    w.close()
    if same_params:
        lst = work / "list.txt"
        lst.write_text("ffconcat version 1.0\n" + f"file '{intro_v.name}'\nduration {float(n_intro / fps):.6f}\n"
                       + f"file '{main_v.as_posix()}'\n", encoding="utf-8")
        sh([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", lst, "-i", final_wav, "-map", "0:v", "-map", "1:a", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out])
        mode = "stream-copy"
    else:
        sh([FF, "-y", "-v", "error", "-i", intro_v, "-i", main_v, "-i", final_wav, "-filter_complex",
            f"[0:v][1:v]concat=n=2:v=1:a=0,{VIDEO_TAIL}[v]", "-map", "[v]", "-map", "2:a"] + X264 + ["-c:a", "aac", "-b:a", "160k",
            "-movflags", "+faststart", out])
        mode = "re-encoded"
    # timeline and subtitles
    tl = load_timeline(main_v) or {"schema_version": 1, "fps": fps_expr(fps), "pieces": [], "offset_frames": 0}
    tl = dict(tl)
    tl["video"] = out.name
    tl["offset_frames"] = int(tl.get("offset_frames", 0)) + n_intro
    tl["intro"] = {"file": str(intro), "frames": n_intro, "seconds": float(n_intro / fps)}
    timeline_path(out).write_text(json.dumps(tl, ensure_ascii=False, indent=1), encoding="utf-8")
    shift = int(round(float(n_intro / fps) * 1000))
    if a.srt:
        cues = parse_srt(Path(a.srt).read_text(encoding="utf-8-sig"))
        blocks = [f"{i + 1}\n{_stamp(c.start_ms + shift)} --> {_stamp(c.end_ms + shift)}\n{c.text}" for i, c in enumerate(cues)]
        (out.parent / (out.stem + ".publication.srt")).write_text("\n\n".join(blocks) + "\n\n", encoding="utf-8")
    # verify
    frames = count_frames(FP, out)
    vd, ad = stream_duration(FP, out, "v"), stream_duration(FP, out, "a")
    t = float(n_intro / fps)
    r = subprocess.run([str(FF), "-v", "error", "-ss", f"{max(0, t - 2):.3f}", "-i", str(out), "-t", "4", "-f", "null", "-"], capture_output=True)

    def mean_db(s, d):
        o = subprocess.run([str(FF), "-hide_banner", "-nostats", "-ss", f"{s:.3f}", "-t", f"{d:.3f}", "-i", str(out), "-vn", "-af", "volumedetect",
                            "-f", "null", "-"], capture_output=True).stderr.decode("utf-8", "replace")
        import re
        mm = re.search(r"mean_volume: (-?[\d.]+) dB", o)
        return float(mm.group(1)) if mm else None

    checks = {
        "frames": {"got": frames, "expected": n_intro + n_main, "passed": frames == n_intro + n_main},
        "durations": {"video": vd, "audio": ad, "passed": vd is not None and ad is not None and abs(vd - ad) <= 2 / float(fps) + 0.03},
        "joint_decode": {"t": t, "errors": r.stderr.decode("utf-8", "replace")[:300], "passed": not r.stderr.strip()},
    }
    report = {"overall": "PASS" if all(c["passed"] for c in checks.values()) else "FAIL", "output": str(out), "mode": mode,
              "intro_seconds": t, "checks": checks,
              "loudness_mean_db": {"intro": mean_db(0, max(1.0, t - 0.6)), "main_first_minute": mean_db(t + 0.5, 60)}}
    ld = report["loudness_mean_db"]
    if ld["intro"] is not None and ld["main_first_minute"] is not None and ld["intro"] - ld["main_first_minute"] > 10:
        report["warning"] = "intro is more than 10 dB louder than the speech; ask the user to listen at the joint or rerun with --intro-gain-db"
    (out.parent / (out.stem + ".join-verify.json")).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["overall"] == "PASS":
        for f in work.iterdir():
            f.unlink()
        work.rmdir()
    log("join", report["overall"], mode, f"{vd:.2f}s")
    return 0 if report["overall"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
