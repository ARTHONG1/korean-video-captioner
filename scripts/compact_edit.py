"""Compact edit of a finished captioned video (references/compact-edit.md).

Long silent screen work is fast-forwarded (4x/8x/16x with a "N배속" badge), pauses are trimmed (short ones
cut, long ones 4x), and speech plays at 1.1x with pitch preserved. Words and caption reading time are protected.

  compact_edit.py detect  --video FINAL.mp4 --run RUN [--srt S] [--words W] [--talk-speed 1.1] [--no-trim]
  compact_edit.py approve --attempt A [--blur START,END,X,Y,W,H]... [--drop I]... [--set I=SPEED]... [--note TEXT]
  compact_edit.py build   --attempt A        (plan, video, audio, mux, remap, verify)
  compact_edit.py plan|video|audio|mux|remap|verify --attempt A
  compact_edit.py map     --timeline VIDEO.timeline.json --times 12.5,300
Every attempt is RUN/compact/attempt-YYYYMMDD-HHMMSS. Inputs are never modified.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import subprocess
import sys
import time
import wave
from fractions import Fraction
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kvc.compact_timeline import kept_count, src_to_out_frames, src_to_out_seconds, talk_modulus  # noqa: E402
from kvc.font import bundled_font  # noqa: E402
from kvc.media_tools import SR, VIDEO_TAIL, X264, count_frames, fps_expr, log, packet_pts, probe, samples_at, sh, silences, stream_duration  # noqa: E402
from kvc.paths import RuntimePaths  # noqa: E402
from kvc.srt import _stamp, parse_srt  # noqa: E402

P = RuntimePaths.discover()
FF, FP = P.ffmpeg, P.ffprobe
DEFAULTS = {"talk_speed": 1.1, "keep": 0.2, "cut_min": 0.6, "fast_min": 3.6, "fast": 4, "trim_pauses": True,
            "ff_min": 20.0, "ff_margin": 0.4, "ff_silence_coverage": 0.8, "chunk_frames": 5400, "reading_cps": 10.0}


def speed_for(length: float) -> int:
    if length < 60:
        return 4
    if length < 300:
        return 8
    return 16


def jload(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def jsave(path: Path, value) -> None:
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def merge(iv):
    out = []
    for a, b in sorted(iv):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def subtract(a, b, prot):
    parts, cur = [], a
    for p, q in prot:
        if q <= cur or p >= b:
            continue
        if p > cur:
            parts.append((cur, p))
        cur = max(cur, q)
        if cur >= b:
            break
    if cur < b:
        parts.append((cur, b))
    return parts


def ts(x: str) -> float:
    h, m, s = x.strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s.replace(",", "."))


def load_cues(srt: Path):
    return parse_srt(Path(srt).read_text(encoding="utf-8-sig")) if srt and Path(srt).is_file() else []


def load_words(path):
    if not path or not Path(path).is_file():
        return []
    data = jload(path)
    items = data.get("words", data) if isinstance(data, dict) else data
    return [(w["start_ms"] / 1000, w["end_ms"] / 1000) for w in items if "start_ms" in w]


def protections(st: dict, ff_margin: float | None = None):
    pad_w = 0.08 if ff_margin is None else ff_margin
    prot = [[a - pad_w, b + pad_w] for a, b in load_words(st.get("words"))]
    for c in load_cues(st.get("srt")):
        a, b = c.start_ms / 1000, c.end_ms / 1000
        if ff_margin is None:
            need = max(1.2, len(c.text.replace(" ", "").replace("\n", "")) / st["params"]["reading_cps"])
            prot.append([a - 0.15, min(b, a + need) + 0.15])
        else:
            prot.append([a - ff_margin, b + ff_margin])
    return merge(prot)


def attempt_settings(a: Path) -> dict:
    return jload(Path(a) / "settings.json")


def pts_of(a: Path, st: dict) -> np.ndarray:
    cache = Path(a) / "pts.npy"
    if cache.is_file():
        return np.load(cache)
    pts = packet_pts(FP, Path(st["video"]))
    np.save(cache, pts)
    return pts


def silence_of(a: Path, st: dict, noise="-40dB", d=1.0):
    cache = Path(a) / f"silence{noise}{d}.json"
    if cache.is_file():
        return [tuple(x) for x in jload(cache)]
    s = silences(FF, Path(st["video"]), noise, d)
    s = [(x, min(y, st["duration"])) for x, y in s]
    jsave(cache, s)
    return s


# ---------------------------------------------------------------- detect / approve
def detect(args) -> None:
    video = Path(args.video).resolve()
    run = Path(args.run).resolve()
    info = probe(FP, video)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    a = run / "compact" / f"attempt-{stamp}"
    a.mkdir(parents=True, exist_ok=False)
    srt = Path(args.srt) if args.srt else next((run / n for n in ("publication.srt", "corrected.srt") if (run / n).is_file()), None)
    words = Path(args.words) if args.words else (run / "words.json" if (run / "words.json").is_file() else None)
    params = dict(DEFAULTS)
    params["talk_speed"] = args.talk_speed
    params["trim_pauses"] = not args.no_trim
    st = {"schema_version": 1, "video": str(video), "run": str(run), "srt": str(srt) if srt else None, "words": str(words) if words else None,
          "width": info["width"], "height": info["height"], "fps": fps_expr(info["fps"]), "duration": info["duration"], "params": params,
          "video_size": video.stat().st_size, "video_mtime": video.stat().st_mtime}
    jsave(a / "settings.json", st)
    log("attempt", a)
    pts = pts_of(a, st)
    end = float(pts[-1])
    prot = protections(st, ff_margin=params["ff_margin"])
    sil = silence_of(a, st)
    gaps = subtract(0.0, end, prot)
    segs = []
    for g0, g1 in gaps:
        if g1 - g0 < params["ff_min"]:
            continue
        covered = sum(max(0.0, min(g1, y) - max(g0, x)) for x, y in sil)
        if covered / (g1 - g0) < params["ff_silence_coverage"]:
            segs.append({"start": round(g0, 3), "end": round(g1, 3), "speed": 1, "skipped": "audio_not_silent",
                         "silence_coverage": round(covered / (g1 - g0), 2)})
            continue
        segs.append({"start": round(g0, 3), "end": round(g1, 3), "speed": speed_for(g1 - g0), "silence_coverage": round(covered / (g1 - g0), 2),
                     "note": "자막·단어 없음 + 무음"})
    plan = {"schema_version": 1, "method": "no words/captions (±0.4 s) for 20 s+, audio silent (-40 dB) for 80%+; 4x <60 s, 8x <5 min, 16x",
            "segments": segs, "privacy_blur": [], "reviewed": False}
    jsave(a / "speed-plan.json", plan)
    review = a / "review"
    review.mkdir()
    font = ImageFont.truetype(str(bundled_font().path), 22)
    for i, s in enumerate(x for x in segs if x["speed"] > 1):
        times = np.linspace(s["start"] + 1, s["end"] - 1, 8)
        ims = []
        for t in times:
            r = subprocess.run([str(FF), "-v", "error", "-ss", f"{t:.2f}", "-i", str(video), "-frames:v", "1", "-vf", "scale=480:-2",
                                "-f", "image2pipe", "-c:v", "png", "-"], capture_output=True)
            if r.stdout:
                import io
                im = Image.open(io.BytesIO(r.stdout)).convert("RGB")
                d = ImageDraw.Draw(im)
                tt = int(t)
                d.rectangle([0, 0, 120, 28], fill=(0, 0, 0))
                d.text((5, 2), f"{tt // 3600}:{tt % 3600 // 60:02d}:{tt % 60:02d}", fill=(255, 230, 0), font=font)
                ims.append(im)
        if ims:
            w, h = ims[0].size
            sheet = Image.new("RGB", (4 * w, 2 * h), (20, 20, 20))
            for k, im in enumerate(ims):
                sheet.paste(im, ((k % 4) * w, (k // 4) * h))
            sheet.save(review / f"segment-{i:02d}.jpg", quality=82)
    log(f"segments {sum(1 for s in segs if s['speed'] > 1)} fast-forward, {sum(1 for s in segs if s['speed'] == 1)} skipped")
    for s in segs:
        log(f"  {s['start']:9.2f}-{s['end']:9.2f} ({(s['end'] - s['start']) / 60:5.1f} min) x{s['speed']} {s.get('skipped', '')}")
    print(json.dumps({"attempt": str(a), "review_sheets": str(review)}, ensure_ascii=False))


def approve(args) -> None:
    a = Path(args.attempt)
    plan = jload(a / "speed-plan.json")
    active = [s for s in plan["segments"] if s["speed"] > 1]
    for spec in args.set or []:
        i, sp = spec.split("=")
        active[int(i)]["speed"] = int(sp)
    for i in sorted(map(int, args.drop or []), reverse=True):
        active[i]["speed"] = 1
        active[i]["skipped"] = "dropped_in_review"
    for b in args.blur or []:
        s, e, x, y, w, h = (float(v) for v in b.split(","))
        plan["privacy_blur"].append({"start": s, "end": e, "box": [int(x), int(y), int(w), int(h)]})
    plan["reviewed"] = True
    plan["review_note"] = args.note or ""
    plan["reviewed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    jsave(a / "speed-plan.json", plan)
    log("approved", sum(1 for s in plan["segments"] if s["speed"] > 1), "segments,", len(plan["privacy_blur"]), "blur boxes")


# ---------------------------------------------------------------- plan
def plan_step(a: Path, force=False) -> None:
    st = attempt_settings(a)
    sp = jload(a / "speed-plan.json")
    if not sp.get("reviewed") and not force:
        raise SystemExit("speed-plan.json is not reviewed; run approve after checking review/*.jpg")
    prm = st["params"]
    fps = Fraction(st["fps"])
    pts = pts_of(a, st)
    N = len(pts)
    fa = lambda t: int(np.searchsorted(pts, t - 1e-6))  # noqa: E731
    segs = sorted((s for s in sp["segments"] if s["speed"] > 1), key=lambda s: s["start"])
    base, cur = [], 0
    for s in segs:
        x, y = fa(s["start"]), fa(s["end"])
        if x > cur:
            base.append(("normal", cur, x, 1))
        if y > max(x, cur):
            base.append(("ff", max(x, cur), y, int(s["speed"])))
        cur = max(cur, y)
    base.append(("normal", cur, N, 1))
    prot = protections(st)
    sil = silence_of(a, st) if prm["trim_pauses"] else []
    pieces = []
    for kind, x, y, k in base:
        if y <= x:
            continue
        if kind == "ff":
            pieces.append({"kind": "ff", "a": x, "b": y, "k": k})
            continue
        t0, t1 = pts[x], pts[y - 1] + float(1 / fps)
        edits = []
        for s, e in sil:
            s, e = max(s, t0), min(e, t1)
            if e - s < 1.0:
                continue
            for p, q in subtract(s + prm["keep"], e - prm["keep"], prot):
                if q - p >= prm["fast_min"]:
                    edits.append((p, q, "fast"))
                elif q - p >= prm["cut_min"]:
                    edits.append((p, q, "cut"))
        cur = x
        for p, q, how in edits:
            fp_, fq = max(fa(p), cur), fa(q)
            if fq - fp_ < 6:
                continue
            if fp_ > cur:
                pieces.append({"kind": "talk", "a": cur, "b": fp_, "k": 1})
            pieces.append({"kind": how, "a": fp_, "b": fq, "k": prm["fast"] if how == "fast" else 0})
            cur = fq
        if y > cur:
            pieces.append({"kind": "talk", "a": cur, "b": y, "k": 1})
    modulus = talk_modulus(prm["talk_speed"])
    o = 0
    for i, p in enumerate(pieces):
        p["idx"] = i
        p["n"] = p["b"] - p["a"]
        p["nout"] = kept_count(p["kind"], p["n"], p["k"], modulus)
        p["out0"] = o
        p["src_t0"] = float(pts[p["a"]])
        p["src_t1"] = float(pts[p["b"]] if p["b"] < N else pts[-1] + float(1 / fps))
        o += p["nout"]
    stat = {}
    for p in pieces:
        d = stat.setdefault(p["kind"], [0, 0.0, 0.0])
        d[0] += 1
        d[1] += p["n"] / fps
        d[2] += p["nout"] / fps
    tl = {"schema_version": 1, "video": "compact.mp4", "fps": st["fps"], "offset_frames": 0, "talk_modulus": modulus,
          "talk_speed": prm["talk_speed"], "source_frames": N, "total_frames": o, "pieces": pieces,
          "privacy_blur": sp.get("privacy_blur", []), "summary": {k: {"pieces": v[0], "source_s": round(float(v[1]), 1), "out_s": round(float(v[2]), 1)} for k, v in stat.items()}}
    jsave(a / "timeline.json", tl)
    log(f"pieces {len(pieces)}  {N / fps / 60:.2f} min -> {o / fps / 60:.2f} min ({o} frames)")
    for k, v in tl["summary"].items():
        log(f"  {k}: {v['pieces']} pieces, {v['source_s'] / 60:.1f} min -> {v['out_s'] / 60:.1f} min")


# ---------------------------------------------------------------- video
def badge(a: Path, sp: int, height: int) -> tuple[Path, int]:
    path = a / f"badge_{sp}.png"
    scale = height / 1080
    font = ImageFont.truetype(str(bundled_font().path), round(34 * scale))
    try:
        font.set_variation_by_name("Bold")
    except Exception:
        pass
    txt = f"{sp}배속"
    tw = font.getlength(txt)
    tri, gap, padx, h = round(18 * scale), round(4 * scale), round(22 * scale), round(60 * scale)
    w = int(padx + tri * 2 + gap + 12 * scale + tw + padx)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, w - 1, h - 1], radius=h // 2, fill=(10, 12, 24, 210), outline=(127, 231, 255, 210), width=max(1, round(2 * scale)))
    for k in range(2):
        x0 = padx + k * (tri + gap)
        d.polygon([(x0, h / 2 - tri / 2 - 3), (x0 + tri, h / 2), (x0, h / 2 + tri / 2 + 3)], fill=(127, 231, 255, 255))
    d.text((padx + 2 * tri + gap + 12 * scale, h / 2), txt, font=font, fill=(255, 255, 255, 255), anchor="lm")
    im.save(path)
    return path, w


def video_step(a: Path) -> None:
    st = attempt_settings(a)
    tl = jload(a / "timeline.json")
    pieces = tl["pieces"]
    fps = Fraction(st["fps"])
    W, H = st["width"], st["height"]
    pts = pts_of(a, st)
    modulus = tl["talk_modulus"]
    groups, cur, acc = [], [], 0
    for p in pieces:
        if p["nout"] == 0 and not cur:
            continue
        cur.append(p)
        acc += p["nout"]
        if acc >= st["params"]["chunk_frames"]:
            groups.append(cur)
            cur, acc = [], 0
    if cur:
        if groups and acc < 120:
            groups[-1].extend(cur)
        else:
            groups.append(cur)
    badges = {k: badge(a, k, H) for k in sorted({p["k"] for p in pieces if p["kind"] == "ff"})}
    chunks_dir = a / "chunks"
    chunks_dir.mkdir(exist_ok=True)
    jobs = []
    for gi, G in enumerate(groups):
        while G and G[-1]["nout"] == 0:
            G.pop()
        if not G:
            continue
        a0, b0 = G[0]["a"], G[-1]["b"]
        o0 = G[0]["out0"]
        nout = sum(p["nout"] for p in G)
        terms = []
        for p in G:
            x, y = p["a"] - a0, p["b"] - 1 - a0
            if p["kind"] == "talk":
                terms.append(f"between(n,{x},{y})*lt(mod(n-{x},{modulus}),{modulus - 1})" if modulus else f"between(n,{x},{y})")
            elif p["kind"] in ("ff", "fast"):
                terms.append(f"between(n,{x},{y})*not(mod(n-{x},{p['k']}))")
        f = f"[0:v]select='{'+'.join(terms)}',setpts=N/({fps_expr(fps)}*TB)"
        lt = lambda frames: (frames - o0) / fps  # noqa: E731
        g_src0, g_src1 = G[0]["src_t0"], G[-1]["src_t1"]
        k_blur = 0
        for b in tl.get("privacy_blur", []):
            s, e = max(b["start"], g_src0), min(b["end"], g_src1)
            if e <= s:
                continue
            bx, by, bw, bh = b["box"]
            t0, t1 = float(lt(src_to_out_frames(tl, s))), float(lt(src_to_out_frames(tl, e)))
            f += (f",split[m{k_blur}][c{k_blur}];[c{k_blur}]crop={bw}:{bh}:{bx}:{by},boxblur=luma_radius=28:luma_power=4:chroma_radius=14:chroma_power=2[bl{k_blur}];"
                  f"[m{k_blur}][bl{k_blur}]overlay={bx}:{by}:enable='between(t,{t0:.4f},{t1:.4f})'")
            k_blur += 1
        f += "[v0]"
        inputs, last, n_in = [], "v0", 1
        for k, (path, w) in badges.items():
            win = "+".join(f"between(t,{float(lt(p['out0'])):.4f},{float(lt(p['out0'] + p['nout'])) - 0.5 / float(fps):.4f})"
                           for p in G if p["kind"] == "ff" and p["k"] == k)
            if not win:
                continue
            inputs += ["-loop", "1", "-framerate", fps_expr(fps), "-i", str(path)]
            f += f";[{last}][{n_in}:v]overlay=x={W - w - round(36 * W / 1920)}:y={round(96 * H / 1080)}:shortest=1:enable='{win}'[v{n_in}]"
            last = f"v{n_in}"
            n_in += 1
        f += f";[{last}]{VIDEO_TAIL}[v]"
        fpath = chunks_dir / f"filter_{gi:02d}.txt"
        fpath.write_text(f, encoding="utf-8")
        out = chunks_dir / f"chunk_{gi:02d}.mp4"
        ss = pts[a0] - 0.25 / float(fps)
        dur = (pts[b0 - 1] - pts[a0]) + 1.0
        cmd = [str(FF), "-y", "-v", "error", "-nostats", "-threads", "4", "-ss", f"{ss:.6f}", "-t", f"{dur:.3f}", "-i", st["video"]] + inputs + [
            "-/filter_complex", str(fpath), "-map", "[v]", "-frames:v", str(nout), "-fps_mode", "passthrough"] + X264 + ["-an", str(out)]
        jobs.append({"gi": gi, "out": str(out), "nout": nout, "o0": o0, "cmd": cmd})
    jsave(a / "chunks.json", [{k: v for k, v in j.items() if k != "cmd"} for j in jobs])
    total = sum(j["nout"] for j in jobs)
    if total != tl["total_frames"]:
        raise SystemExit(f"chunk frames {total} != timeline {tl['total_frames']}")
    log(f"{len(jobs)} chunks, {total} frames")
    for j in jobs:
        if Path(j["out"]).exists() and count_frames(FP, Path(j["out"])) == j["nout"]:
            continue
        r = subprocess.run(j["cmd"], capture_output=True)
        if r.returncode != 0:
            sys.stderr.write(r.stderr.decode("utf-8", "replace")[-2000:])
            raise SystemExit(f"chunk {j['gi']} failed")
        got = count_frames(FP, Path(j["out"]))
        if got != j["nout"]:
            raise SystemExit(f"chunk {j['gi']} frames {got} != {j['nout']}")
        log(f"chunk {j['gi']:02d} ok ({j['nout']} frames) {j['gi'] + 1}/{len(jobs)}")
    lst = ["ffconcat version 1.0"] + [f"file '{Path(j['out']).name}'" for j in jobs]
    (chunks_dir / "chunks.txt").write_text("\n".join(lst) + "\n", encoding="utf-8")
    sh([FF, "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", chunks_dir / "chunks.txt", "-c", "copy", a / "video.mp4"])
    got = count_frames(FP, a / "video.mp4")
    if got != total:
        raise SystemExit(f"joined video frames {got} != {total}")
    for j in jobs:
        Path(j["out"]).unlink(missing_ok=True)
    log("video done", got, "frames")


# ---------------------------------------------------------------- audio
def audio_step(a: Path) -> None:
    st = attempt_settings(a)
    tl = jload(a / "timeline.json")
    pieces = tl["pieces"]
    fps = Fraction(st["fps"])
    mainwav, finalwav = a / "main_pts.wav", a / "compact-audio.wav"
    if not mainwav.exists():
        sh([FF, "-y", "-v", "error", "-i", st["video"], "-vn", "-af", "aresample=async=1:min_hard_comp=0.001:first_pts=0", "-ac", "2",
            "-ar", str(SR), "-c:a", "pcm_s16le", mainwav])
    src = wave.open(str(mainwav), "rb")
    nsrc = src.getnframes()

    def read(s0, s1):
        out = np.zeros((max(0, s1 - s0), 2), np.int16)
        if s0 < nsrc and s1 > s0:
            src.setpos(max(0, s0))
            x = np.frombuffer(src.readframes(min(s1, nsrc) - s0), np.int16).reshape(-1, 2)
            out[:len(x)] = x
        return out

    def ramp(x, n):
        y = x.astype(np.float32)
        n = min(n, len(y) // 2)
        if n > 0:
            r = np.linspace(0, 1, n)[:, None]
            y[:n] *= r
            y[-n:] *= r[::-1]
        return y.astype(np.int16)

    tin, tout = a / "tmp_in.wav", a / "tmp_out.wav"

    def stretch(x, k, nout):
        if len(x) == 0:
            return np.zeros((nout, 2), np.int16)
        w = wave.open(str(tin), "wb")
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(x.tobytes())
        w.close()
        chain, kk = [], k
        while kk > 2.0:
            chain.append("atempo=2.0")
            kk /= 2.0
        while kk < 0.5:
            chain.append("atempo=0.5")
            kk /= 0.5
        chain.append(f"atempo={kk:.6f}")
        sh([FF, "-y", "-v", "error", "-i", tin, "-af", ",".join(chain), "-c:a", "pcm_s16le", tout])
        w = wave.open(str(tout), "rb")
        y = np.frombuffer(w.readframes(w.getnframes()), np.int16).reshape(-1, 2)
        w.close()
        z = np.zeros((nout, 2), np.int16)
        z[:min(len(y), nout)] = y[:nout]
        return z

    sidx = lambda t: int(round(t * SR))  # noqa: E731
    dst = wave.open(str(finalwav), "wb")
    dst.setnchannels(2)
    dst.setsampwidth(2)
    dst.setframerate(SR)
    written = 0
    for p in pieces:
        if p["kind"] == "cut":
            continue
        nout = samples_at(p["out0"] + p["nout"], fps) - samples_at(p["out0"], fps)
        x = read(sidx(p["src_t0"]), sidx(p["src_t1"]))
        if p["kind"] in ("ff", "fast"):
            z = ramp(stretch(x, p["k"], nout), 240)
        else:
            z = ramp(stretch(x, max(1e-6, len(x) / max(1, nout)), nout), 96)
        dst.writeframes(z.tobytes())
        written += len(z)
    dst.close()
    src.close()
    for t in (tin, tout, mainwav):
        t.unlink(missing_ok=True)
    expect = samples_at(tl["total_frames"], fps)
    if written != expect:
        raise SystemExit(f"audio samples {written} != {expect}")
    log("audio done", written, "samples")


# ---------------------------------------------------------------- mux / remap
def mux_step(a: Path) -> None:
    st = attempt_settings(a)
    out = a / "compact.mp4"
    if out.exists():
        raise SystemExit(f"refusing to overwrite {out}")
    sh([FF, "-y", "-v", "error", "-i", a / "video.mp4", "-i", a / "compact-audio.wav", "-map", "0:v", "-map", "1:a", "-c:v", "copy",
        "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out])
    tl = jload(a / "timeline.json")
    tl["video"] = out.name
    tl["source_video"] = st["video"]
    jsave(a / "compact.timeline.json", tl)
    (a / "video.mp4").unlink(missing_ok=True)
    log("mux done", out)


def remap_srt(src: Path, dst: Path, tl: dict) -> int:
    cues = parse_srt(Path(src).read_text(encoding="utf-8-sig"))
    blocks, prev = [], 0
    for c in cues:
        a = max(prev, int(round(src_to_out_seconds(tl, c.start_ms / 1000) * 1000)))
        b = max(a + 1, int(round(src_to_out_seconds(tl, c.end_ms / 1000) * 1000)))
        blocks.append(f"{len(blocks) + 1}\n{_stamp(a)} --> {_stamp(b)}\n{c.text}")
        prev = b
    Path(dst).write_text("\n\n".join(blocks) + "\n\n", encoding="utf-8")
    return len(blocks)


def remap_step(a: Path) -> None:
    st = attempt_settings(a)
    tl = jload(a / "compact.timeline.json")
    if st.get("srt"):
        n = remap_srt(Path(st["srt"]), a / "publication-compact.srt", tl)
        log("srt cues", n)


# ---------------------------------------------------------------- verify
def verify_step(a: Path) -> dict:
    st = attempt_settings(a)
    tl = jload(a / "compact.timeline.json")
    fps = Fraction(st["fps"])
    out = a / "compact.mp4"
    main = Path(st["video"])
    checks = {}
    frames = count_frames(FP, out)
    checks["frames"] = {"got": frames, "expected": tl["total_frames"], "passed": frames == tl["total_frames"]}
    vd, ad = stream_duration(FP, out, "v"), stream_duration(FP, out, "a")
    checks["durations"] = {"video": vd, "audio": ad, "passed": vd is not None and ad is not None and abs(vd - ad) <= 2 / float(fps) + 0.03}
    errs = []
    for j in jload(a / "chunks.json"):
        t = float(j["o0"] / fps)
        r = subprocess.run([str(FF), "-v", "error", "-ss", f"{max(0, t - 2):.3f}", "-i", str(out), "-t", "4", "-f", "null", "-"], capture_output=True)
        if r.stderr.strip():
            errs.append({"t": t, "err": r.stderr.decode("utf-8", "replace")[:200]})
    checks["joins_decode"] = {"joins": len(jload(a / "chunks.json")), "errors": errs, "passed": not errs}
    src_size_ok = main.stat().st_size == st["video_size"] and abs(main.stat().st_mtime - st["video_mtime"]) < 1
    checks["source_unchanged"] = {"passed": src_size_ok}
    # speech sync: compare loudness envelopes of the same speech in source and output
    HOP = 240

    def aud(path, t, d):
        r = subprocess.run([str(FF), "-v", "error", "-i", str(path), "-ss", f"{t:.6f}", "-t", f"{d:.6f}", "-map", "0:a", "-ac", "1", "-ar", str(SR),
                            "-f", "f32le", "-"], capture_output=True)
        return np.frombuffer(r.stdout, np.float32)

    def env(x):
        n = len(x) // HOP
        return np.log10(np.sqrt((x[: n * HOP].reshape(n, HOP) ** 2).mean(1) + 1e-10)) if n else np.zeros(0)

    random.seed(11)
    cands = [p for p in tl["pieces"] if p["kind"] == "talk" and p["nout"] / fps > 6]
    res = []
    for p in random.sample(cands, min(12, len(cands))):
        k = (p["src_t1"] - p["src_t0"]) / float(p["nout"] / fps)
        s0, D = p["src_t0"] + 0.8, min(4.0, (p["src_t1"] - p["src_t0"]) - 1.6)
        se = env(aud(main, s0, D))
        if len(se) < 20:
            continue
        tt = np.arange(0, len(se) / k) * k
        se_k = np.interp(tt, np.arange(len(se)), se)
        o_t, pad = float(p["out0"] / fps) + 0.8 / k, 0.2
        oe = env(aud(out, o_t - pad, D / k + 2 * pad))
        x = se_k - se_k.mean()
        best, lag = -9.0, 0
        for L in range(0, max(0, len(oe) - len(x)) + 1):
            y = oe[L:L + len(x)]
            if len(y) < len(x):
                break
            y = y - y.mean()
            c = float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))
            if c > best:
                best, lag = c, L
        res.append({"piece": p["idx"], "out_s": round(o_t, 2), "offset_ms": round((lag * HOP / SR - pad) * 1000, 1), "corr": round(best, 2)})
    good = [r for r in res if r["corr"] > 0.6]
    worst = max((abs(r["offset_ms"]) for r in good), default=None)
    checks["speech_sync"] = {"samples": res, "clear": len(good), "max_offset_ms": worst, "passed": worst is None or worst <= 25}
    overall = "PASS" if all(c["passed"] for c in checks.values()) else "FAIL"
    report = {"overall": overall, "compact": str(out), "duration_s": vd, "source_duration_s": st["duration"], "checks": checks,
              "summary": tl.get("summary")}
    jsave(a / "compact-verify.json", report)
    log("verify", overall, json.dumps({k: v["passed"] for k, v in checks.items()}))
    return report


def map_cmd(args) -> None:
    tl = jload(args.timeline)
    for t in (float(x) for x in args.times.split(",")):
        o = src_to_out_seconds(tl, t)
        print(f"{t:.3f} -> {o:.3f}  ({int(o) // 60}:{int(o) % 60:02d})")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("detect")
    d.add_argument("--video", required=True)
    d.add_argument("--run", required=True)
    d.add_argument("--srt")
    d.add_argument("--words")
    d.add_argument("--talk-speed", type=float, default=DEFAULTS["talk_speed"])
    d.add_argument("--no-trim", action="store_true")
    ap_ = sub.add_parser("approve")
    ap_.add_argument("--attempt", required=True)
    ap_.add_argument("--blur", action="append")
    ap_.add_argument("--drop", action="append")
    ap_.add_argument("--set", action="append")
    ap_.add_argument("--note")
    for name in ("build", "plan", "video", "audio", "mux", "remap", "verify"):
        s = sub.add_parser(name)
        s.add_argument("--attempt", required=True)
        s.add_argument("--force", action="store_true", help="plan without review (tests only)")
    m = sub.add_parser("map")
    m.add_argument("--timeline", required=True)
    m.add_argument("--times", required=True)
    args = ap.parse_args()
    if args.cmd == "detect":
        detect(args)
    elif args.cmd == "approve":
        approve(args)
    elif args.cmd == "map":
        map_cmd(args)
    else:
        a = Path(args.attempt).resolve()
        steps = {"plan": lambda: plan_step(a, args.force), "video": lambda: video_step(a), "audio": lambda: audio_step(a),
                 "mux": lambda: mux_step(a), "remap": lambda: remap_step(a), "verify": lambda: verify_step(a)}
        order = ["plan", "video", "audio", "mux", "remap", "verify"] if args.cmd == "build" else [args.cmd]
        for name in order:
            steps[name]()
        if args.cmd in ("build", "verify"):
            return 0 if jload(a / "compact-verify.json")["overall"] == "PASS" else 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
