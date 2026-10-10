"""Natural pause and filler editing for a captioned run.

    analyze  --video V --run RUN            measure audio/screen, list filler candidates (new attempt dir)
    plan     --attempt DIR --filler-review F  build and re-validate the cut plan (or --no-fillers)
    preview  --attempt DIR                   render before/after one-minute previews around the densest cuts
    render   --attempt DIR                   render edited.mp4, remap subtitles/tips, verify every joint

Source video, run files, and earlier attempts are never modified.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from kvc.paths import RuntimePaths
from kvc.pause_plan import (PauseConfig, filler_candidates, plan_pause_edits, plan_to_json, validate_filler_review,
                            validate_plan)
from kvc.pause_render import (build_audio, envelope_of, gray_frame, open_pcm, probe, verify_joints, verify_sync,
                              video_command, write_filter_script)
from kvc.pause_signal import FRAME_FPS, FRAME_H, FRAME_W, Levels, changed_pixels, envelope_db, estimate_levels, region_masks, speech_mask
from kvc.pause_timeline import (Timeline, output_frames, pieces_from_cuts, remap_ass, remap_cues, remap_words,
                                strip_removed_words, window_pieces)
from kvc.srt import parse_srt, write_srt

SEGMENT_FRAMES_S = 300
VERIFY_FRAME_SAMPLES = 24


def _write(path: Path, value) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def _read(path: Path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def _progress(attempt: Path, stage: str, percent: float, **extra) -> None:
    _write(attempt / "pause-progress.json", {"stage": stage, "percent": round(percent, 1),
                                             "updated_at": datetime.now().isoformat(timespec="seconds"), **extra})


def _fingerprint(path: Path) -> dict:
    stat = path.stat()
    return {"path": str(path.resolve()), "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _stamp(seconds: float) -> str:
    minutes, secs = divmod(max(0.0, seconds), 60)
    return f"{int(minutes):02d}:{secs:05.2f}"


class FrameActivity:
    """Screen/webcam change measured on 192x108 gray frames sampled at 10 fps."""

    def __init__(self, path: Path):
        count = path.stat().st_size // (FRAME_W * FRAME_H)
        self.frames = np.memmap(path, dtype=np.uint8, mode="r", shape=(count, FRAME_H, FRAME_W))
        self.screen, self.cam = region_masks()
        self.cam_area = int(self.cam.sum())
        diffs = np.zeros(max(0, count - 1), dtype=np.int32)
        for start in range(0, count - 1, 2000):
            stop = min(count - 1, start + 2000)
            a = self.frames[start:stop].astype(np.int16)
            b = self.frames[start + 1:stop + 1].astype(np.int16)
            diffs[start:stop] = ((np.abs(a - b) > 12) & self.screen).reshape(stop - start, -1).sum(axis=1)
        self.diffs = diffs

    def _index(self, seconds: float) -> int:
        return int(min(max(0, int(seconds * FRAME_FPS)), len(self.frames) - 1))

    def activity_between(self, start_s: float, end_s: float) -> int:
        a, b = self._index(start_s - 0.1), self._index(end_s + 0.1)
        return int(self.diffs[a:max(a + 1, b)].max()) if len(self.diffs) else 0

    def jump(self, start_s: float, end_s: float) -> tuple[int, float]:
        before, after = self.frames[self._index(start_s - 0.05)], self.frames[self._index(end_s + 0.05)]
        screen = changed_pixels(before, after, self.screen)
        cam = changed_pixels(before, after, self.cam) / max(1, self.cam_area)
        return screen, cam


def _media(ffprobe: Path, video: Path) -> dict:
    info = probe(ffprobe, video)
    streams = info["streams"]
    v = next(s for s in streams if s["codec_type"] == "video")
    a = next((s for s in streams if s["codec_type"] == "audio"), None)
    if a is None:
        raise SystemExit("PAUSE_BLOCKED video has no audio stream")
    fps = Fraction(v["avg_frame_rate"])
    if fps != Fraction(v["r_frame_rate"]):
        raise SystemExit("PAUSE_BLOCKED variable frame rate video; frame-exact editing is not safe")
    if abs(float(v.get("start_time", 0) or 0)) > 0.001 or abs(float(a.get("start_time", 0) or 0)) > 0.05:
        raise SystemExit("PAUSE_BLOCKED video/audio do not start at 0; remux the source before pause editing")
    frames = int(v["nb_read_packets"])
    if abs(frames / float(fps) - float(info["format"]["duration"])) > 0.2:
        raise SystemExit("PAUSE_BLOCKED frame count does not match duration (irregular timestamps)")
    return {"fps": fps, "frames": frames, "width": v["width"], "height": v["height"],
            "sample_rate": int(a["sample_rate"]), "channels": int(a["channels"]), "duration": float(info["format"]["duration"])}


def cmd_analyze(args) -> None:
    paths = RuntimePaths.discover()
    video, run = Path(args.video), Path(args.run)
    words = _read(run / "words.json")["words"]
    cues = parse_srt((run / "corrected.srt").read_text(encoding="utf-8-sig"))
    attempt = run / "pause-edit" / datetime.now().strftime("attempt-%Y%m%d-%H%M%S")
    attempt.mkdir(parents=True)
    _progress(attempt, "probe", 0)
    media = _media(paths.ffprobe, video)
    _progress(attempt, "extract", 5)
    subprocess.run([str(paths.ffmpeg), "-y", "-v", "error", "-i", str(video),
                    "-map", "0:a:0", "-ac", str(media["channels"]), "-ar", str(media["sample_rate"]), "-c:a", "pcm_s16le", str(attempt / "source.wav"),
                    "-map", "0:v:0", "-vf", f"fps={FRAME_FPS},scale={FRAME_W}:{FRAME_H}:flags=area,format=gray",
                    "-f", "rawvideo", str(attempt / "frames.gray")], check=True)
    _progress(attempt, "measure", 60)
    pcm, rate, _ = open_pcm(attempt / "source.wav")
    env = envelope_db(pcm, rate)
    del pcm
    np.save(attempt / "envelope.npy", env)
    levels = estimate_levels(env, speech_mask(len(env), [(w["start_ms"] / 1000, w["end_ms"] / 1000) for w in words]))
    candidates = filler_candidates(words, cues)
    ordered = sorted(words, key=lambda w: w["start_ms"])
    position = {w["id"]: i for i, w in enumerate(ordered)}
    for item in candidates:
        i = position[item["word_ids"][0]]
        j = position[item["word_ids"][-1]]
        item["before"] = " ".join(w["text"].strip() for w in ordered[max(0, i - 6):i])
        item["after"] = " ".join(w["text"].strip() for w in ordered[j + 1:j + 7])
    _write(attempt / "filler-candidates.json", {"schema_version": 1, "candidates": candidates})
    _write(attempt / "filler-review.template.json", {"schema_version": 1, "items": [
        {"id": c["id"], "word_ids": c["word_ids"], "decision": "", "reason": ""} for c in candidates]})
    _write(attempt / "analysis.json", {"schema_version": 1, "video": _fingerprint(video), "run": str(run.resolve()),
                                      "fps": f"{media['fps'].numerator}/{media['fps'].denominator}",
                                      "total_frames": media["frames"], "sample_rate": rate, "channels": media["channels"],
                                      "width": media["width"], "height": media["height"], "levels": levels.as_dict(),
                                      "words_sha": _fingerprint(run / "words.json"), "cues_sha": _fingerprint(run / "corrected.srt")})
    _progress(attempt, "analyzed", 100, filler_candidates=len(candidates), separable=levels.separable)
    print(json.dumps({"attempt": str(attempt), "filler_candidates": len(candidates), "levels": levels.as_dict()}, ensure_ascii=False))


def _load(attempt: Path):
    analysis = _read(attempt / "analysis.json")
    run = Path(analysis["run"])
    video = Path(analysis["video"]["path"])
    if _fingerprint(video) != analysis["video"]:
        raise SystemExit("PAUSE_BLOCKED source video changed since analyze; run analyze again")
    for key, name in (("words_sha", "words.json"), ("cues_sha", "corrected.srt")):
        if _fingerprint(run / name) != analysis[key]:
            raise SystemExit(f"PAUSE_BLOCKED {name} changed since analyze; run analyze again")
    words = _read(run / "words.json")["words"]
    cues = parse_srt((run / "corrected.srt").read_text(encoding="utf-8-sig"))
    lv = analysis["levels"]
    levels = Levels(lv["floor_db"], lv["speech_db"], lv["threshold_db"], lv["separable"])
    return analysis, run, video, words, cues, np.load(attempt / "envelope.npy"), levels


def cmd_plan(args) -> None:
    attempt = Path(args.attempt)
    analysis, run, video, words, cues, env, levels = _load(attempt)
    config = PauseConfig.for_strength(args.strength)
    candidates = _read(attempt / "filler-candidates.json")["candidates"]
    if args.no_fillers:
        accepted, problems = [], []
    else:
        if not args.filler_review:
            raise SystemExit("PAUSE_BLOCKED --filler-review is required (or pass --no-fillers)")
        accepted, problems = validate_filler_review(candidates, _read(Path(args.filler_review)))
    activity = FrameActivity(attempt / "frames.gray")
    result = plan_pause_edits(words=words, cues=cues, env=env, levels=levels, activity=activity,
                              fps=Fraction(analysis["fps"]), total_frames=analysis["total_frames"], config=config,
                              removals=accepted, review_problems=problems)
    plan = plan_to_json(result, fps=Fraction(analysis["fps"]), total_frames=analysis["total_frames"], config=config,
                        levels=levels, source=analysis["video"], candidates=candidates, filler_accepted=accepted)
    errors = validate_plan(plan, words, env, levels, config)
    if errors:
        plan["status"] = "INVALID"
        plan["problems"].extend({"code": "validation", "detail": e} for e in errors)
    by_cue = {}
    for cut in plan["cuts"]:
        if cut["word_ids"]:
            item = next(c for c in candidates if c["id"] == cut["candidate_id"])
            by_cue.setdefault(item["cue_id"], []).append(item["text"])
    plan["caption_text_checks"] = [{"cue_id": cue_id, "removed": texts,
                                    "cue_text": next((c.text for c in cues if c.id == cue_id), "")} for cue_id, texts in by_cue.items()]
    _write(attempt / "pause-plan.json", plan)
    lines = [f"# 컷 목록 ({plan['status']})", f"컷 {plan['summary']['cuts']}개, {plan['summary']['removed_s']}초 감소 "
             f"({plan['summary']['reduction_ratio']:.1%})", ""]
    for cut in plan["cuts"]:
        label = {"pause": "공백", "filler": "군말", "repetition": "반복"}[cut["kind"]]
        lines.append(f"{cut['id']}  {_stamp(cut['start_s'])}  {label:<3} {cut['gap_s']:.2f}초 → {cut['kept_pause_s']:.2f}초 ({cut['context']})")
    (attempt / "cut-list.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": plan["status"], "summary": plan["summary"], "problems": plan["problems"][:10]}, ensure_ascii=False, indent=2))
    if plan["status"] not in {"PASS", "NO_CUTS"}:
        raise SystemExit(2)


def _pieces(plan: dict) -> list[dict]:
    return pieces_from_cuts(plan["total_frames"], [(c["start_frame"], c["end_frame"]) for c in plan["cuts"]])


def _frame_count(ffprobe: Path, path: Path) -> int:
    info = probe(ffprobe, path)
    return int(next(s for s in info["streams"] if s["codec_type"] == "video")["nb_read_packets"])


def cmd_preview(args) -> None:
    attempt = Path(args.attempt)
    analysis, run, video, words, cues, env, levels = _load(attempt)
    plan = _read(attempt / "pause-plan.json")
    if plan["status"] != "PASS":
        raise SystemExit(f"PAUSE_BLOCKED plan status is {plan['status']}")
    paths = RuntimePaths.discover()
    fps = Fraction(plan["fps"])
    pieces = _pieces(plan)
    out_dir = attempt / "previews"
    out_dir.mkdir(exist_ok=True)
    window = int(args.length * float(fps))
    starts = []
    cut_frames = [c["start_frame"] for c in plan["cuts"]]
    for _ in range(args.count):
        best, best_n = None, 0
        for frame in cut_frames:
            s = max(0, frame - window // 6)
            if any(abs(s - o) < window for o in starts):
                continue
            n = sum(1 for f in cut_frames if s <= f < s + window)
            if n > best_n:
                best, best_n = s, n
        if best is None:
            break
        starts.append(min(best, max(0, plan["total_frames"] - window)))
    pcm, rate, _ = open_pcm(attempt / "source.wav")
    notes = ["# 미리보기 확인표", "각 번호의 before(원본)와 after(편집본)를 비교해 들어 주세요.", ""]
    for number, first in enumerate(sorted(starts), 1):
        last = min(plan["total_frames"], first + window)
        local = window_pieces(pieces, first, last)
        wav = out_dir / f"preview-{number:02d}.wav"
        build_audio(pcm, rate, local, fps, wav)
        after = out_dir / f"preview-{number:02d}-after.mp4"
        _encode_with_audio(paths, video, local, fps, first, last, after, wav, crf=20)
        wav.unlink(missing_ok=True)
        before = out_dir / f"preview-{number:02d}-before.mp4"
        subprocess.run([str(paths.ffmpeg), "-y", "-v", "error", "-ss", f"{first / float(fps):.6f}", "-t", f"{(last - first) / float(fps):.6f}",
                        "-i", str(video), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "192k", str(before)], check=True)
        notes.append(f"## {number}. 원본 {_stamp(first / float(fps))}부터 {args.length:g}초 (before/after: preview-{number:02d}-*.mp4)")
        for cut in plan["cuts"]:
            if first <= cut["start_frame"] < last:
                out_at = (sum(min(p["src_end"], cut["start_frame"]) - p["src_start"] for p in local if p["src_start"] < cut["start_frame"])) / float(fps)
                label = {"pause": "공백", "filler": "군말", "repetition": "반복"}[cut["kind"]]
                notes.append(f"- after {_stamp(out_at)}  {label} {cut['gap_s']:.2f}초 → {cut['kept_pause_s']:.2f}초")
        notes.append("")
    del pcm
    (out_dir / "preview-notes.md").write_text("\n".join(notes), encoding="utf-8")
    _write(out_dir / "preview-manifest.json", {"schema_version": 1, "plan_sha": _fingerprint(attempt / "pause-plan.json"),
                                               "previews": len(starts)})
    print(json.dumps({"previews": str(out_dir), "count": len(starts)}, ensure_ascii=False))


def _encode_with_audio(paths, video, local, fps, first, last, output, wav, crf):
    script = output.with_name(output.stem + ".filter.txt")
    write_filter_script(script, local, fps)
    seek = max(0.0, (first - 2) / float(fps))
    length = (last - first + 4) / float(fps)
    subprocess.run(video_command(paths.ffmpeg, video, wav, script, output, fps, seek_s=seek, length_s=length, crf=crf), check=True)
    script.unlink(missing_ok=True)


def _encode_video(paths, video, pieces, fps, first, last, output, crf, progress):
    local = window_pieces(pieces, first, last)
    script = output.with_name(output.stem + ".filter.txt")
    write_filter_script(script, local, fps)
    seek = max(0.0, (first - 2) / float(fps))
    length = (last - first + 4) / float(fps)
    command = [str(paths.ffmpeg), "-y", "-v", "error", "-progress", str(progress), "-nostats",
               "-ss", f"{seek:.6f}", "-t", f"{length:.6f}", "-copyts", "-i", str(video),
               "-/filter_complex", str(script), "-map", "[v]", "-an", "-r", f"{fps.numerator}/{fps.denominator}",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(output)]
    subprocess.run(command, check=True)
    script.unlink(missing_ok=True)
    return output_frames(local)


def cmd_render(args) -> None:
    attempt = Path(args.attempt)
    analysis, run, video, words, cues, env, levels = _load(attempt)
    plan = _read(attempt / "pause-plan.json")
    if plan["status"] != "PASS":
        raise SystemExit(f"PAUSE_BLOCKED plan status is {plan['status']}")
    manifest = attempt / "previews" / "preview-manifest.json"
    if not args.skip_preview and (not manifest.is_file() or _read(manifest)["plan_sha"] != _fingerprint(attempt / "pause-plan.json")):
        raise SystemExit("PAUSE_BLOCKED render previews of this plan first and get the user's approval (or --skip-preview)")
    if (attempt / "edited.mp4").exists():
        raise SystemExit("PAUSE_BLOCKED edited.mp4 already exists in this attempt")
    paths = RuntimePaths.discover()
    fps = Fraction(plan["fps"])
    pieces = _pieces(plan)
    expected_total = output_frames(pieces)
    work = attempt / "render-parts"
    work.mkdir(exist_ok=True)

    _progress(attempt, "audio", 1)
    pcm, rate, channels = open_pcm(attempt / "source.wav")
    audio = work / "edited-audio.wav"
    samples = build_audio(pcm, rate, pieces, fps, audio)
    del pcm
    expected_samples = sum(round((p["src_end"] - p["src_start"]) * rate / fps) for p in pieces)
    if abs(samples - expected_samples) > len(pieces):
        raise SystemExit(f"PAUSE_FAILED audio length {samples} != {expected_samples}")

    step = int(SEGMENT_FRAMES_S * float(fps))
    windows = [(s, min(plan["total_frames"], s + step)) for s in range(0, plan["total_frames"], step)]
    listing = []
    done_frames = 0
    for index, (first, last) in enumerate(windows):
        segment = work / f"segment-{index:03d}.mp4"
        expected = output_frames(window_pieces(pieces, first, last))
        if expected == 0:
            continue
        if not (segment.is_file() and _frame_count(paths.ffprobe, segment) == expected):
            progress = work / f"segment-{index:03d}.progress"
            _progress(attempt, "video", 5 + 85 * done_frames / expected_total, segment=index + 1, segments=len(windows))
            _encode_video(paths, video, pieces, fps, first, last, segment, args.crf, progress)
            progress.unlink(missing_ok=True)
            actual = _frame_count(paths.ffprobe, segment)
            if actual != expected:
                raise SystemExit(f"PAUSE_FAILED segment {index} has {actual} frames, expected {expected}")
        done_frames += expected
        listing.append(f"file '{segment.name}'")
    (work / "segments.txt").write_text("\n".join(listing) + "\n", encoding="utf-8")
    _progress(attempt, "mux", 91)
    staged = attempt / "edited.partial.mp4"
    subprocess.run([str(paths.ffmpeg), "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(work / "segments.txt"),
                    "-i", str(audio), "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart", str(staged)], check=True)

    _progress(attempt, "verify", 93)
    timeline = Timeline(pieces, fps)
    report = _verify(paths, video, staged, attempt, plan, pieces, timeline, levels, rate, channels, expected_total, env)
    _write(attempt / "pause-verify.json", report)
    if report["overall"] != "PASS":
        raise SystemExit("PAUSE_FAILED verification failed; see pause-verify.json (edited.partial.mp4 kept for inspection)")
    os.replace(staged, attempt / "edited.mp4")
    _write(attempt / "timeline-map.json", timeline.to_json())
    _remap(run, attempt, timeline, plan)
    shutil.rmtree(work, ignore_errors=True)
    for name in ("source.wav", "frames.gray"):
        (attempt / name).unlink(missing_ok=True)
    _progress(attempt, "done", 100)
    print(json.dumps({"edited": str(attempt / "edited.mp4"), "verify": report["overall"],
                      "duration_s": report["output_duration_s"], "removed_s": plan["summary"]["removed_s"]}, ensure_ascii=False))


def _verify(paths, video, output, attempt, plan, pieces, timeline, levels, rate, channels, expected_total, src_env) -> dict:
    checks = []
    fps = Fraction(plan["fps"])
    frames = _frame_count(paths.ffprobe, output)
    checks.append({"name": "frame_count", "passed": frames == expected_total, "detail": {"actual": frames, "expected": expected_total}})
    info = probe(paths.ffprobe, output)
    audio_stream = next(s for s in info["streams"] if s["codec_type"] == "audio")
    duration = float(info["format"]["duration"])
    expected_s = expected_total / float(fps)
    checks.append({"name": "duration", "passed": abs(duration - expected_s) <= 0.1,
                   "detail": {"actual_s": duration, "expected_s": round(expected_s, 3)}})
    out_env = envelope_of(paths.ffmpeg, output, attempt, rate, channels)
    checks.append({"name": "audio_length", "passed": abs(len(out_env) * 0.01 - expected_s) <= 0.1,
                   "detail": {"audio_s": round(len(out_env) * 0.01, 3), "channels": audio_stream.get("channels")}})
    joint_failures = verify_joints(out_env, timeline.joints(), levels.threshold_db)
    checks.append({"name": "quiet_joints", "passed": not joint_failures, "detail": {"joints": len(timeline.joints()), "failures": joint_failures[:20]}})
    sync = verify_sync(src_env, out_env, pieces, fps, levels.floor_db)
    checks.append({"name": "audio_sync", "passed": not sync["failures"], "detail": sync})
    frame_failures = []
    joints = list(zip(pieces, pieces[1:]))
    sample = joints if len(joints) <= VERIFY_FRAME_SAMPLES else [joints[int(i * len(joints) / VERIFY_FRAME_SAMPLES)] for i in range(VERIFY_FRAME_SAMPLES)]
    for left, right in sample:
        for src_frame, out_frame in ((left["src_end"] - 1, right["out_start"] - 1), (right["src_start"], right["out_start"])):
            a = gray_frame(paths.ffmpeg, video, max(0.0, src_frame / float(fps) - 0.001))
            b = gray_frame(paths.ffmpeg, output, max(0.0, out_frame / float(fps) - 0.001))
            diff = float(np.mean(np.abs(a.astype(np.int16) - b.astype(np.int16))))
            if diff > 6.0:
                frame_failures.append({"out_frame": out_frame, "src_frame": src_frame, "mean_diff": round(diff, 2)})
    checks.append({"name": "joint_frames_match_source", "passed": not frame_failures,
                   "detail": {"sampled_joints": len(sample), "failures": frame_failures}})
    src_now = _fingerprint(video)
    checks.append({"name": "source_unchanged", "passed": src_now == plan["source"], "detail": src_now})
    return {"schema_version": 1, "overall": "PASS" if all(c["passed"] for c in checks) else "FAIL",
            "output_duration_s": round(duration, 3), "checks": checks}


def _remap(run: Path, attempt: Path, timeline: Timeline, plan: dict) -> None:
    out = attempt / "remapped"
    out.mkdir(exist_ok=True)
    report = {"schema_version": 1, "files": {}}
    candidates = {c["id"]: c for c in _read(attempt / "filler-candidates.json")["candidates"]}
    removed = [candidates[cut["candidate_id"]] for cut in plan["cuts"] if cut.get("candidate_id") in candidates]
    for name in ("corrected.srt", "caption-without-markers.srt", "publication.srt"):
        path = run / name
        if path.is_file() and path.stat().st_size:
            cues = parse_srt(path.read_text(encoding="utf-8-sig"))
            unresolved = []
            edited = []
            for cue in cues:
                # Match removed words to caption cues by source time, so every subtitle file is covered.
                inside = [item for item in removed
                          if item["start_ms"] < cue.end_ms and item["end_ms"] > cue.start_ms]
                text, missing = strip_removed_words(cue.text, inside)
                unresolved.extend(missing)
                edited.append(type(cue)(cue.id, cue.start_ms, cue.end_ms, text or cue.text))
            cues = edited
            mapped, dropped = remap_cues(cues, timeline)
            mapped = [cue for cue in mapped if cue.text.strip()]
            (out / name).write_text(write_srt(mapped), encoding="utf-8-sig")
            report["files"][name] = {"cues": len(mapped), "dropped_cue_ids": dropped,
                                     "filler_text_not_in_caption": unresolved}
    if (run / "tips.ass").is_file():
        text, dropped = remap_ass((run / "tips.ass").read_text(encoding="utf-8"), timeline)
        (out / "tips.ass").write_text(text, encoding="utf-8")
        report["files"]["tips.ass"] = {"dropped_events": dropped}
    if (run / "words.json").is_file():
        payload, dropped = remap_words(_read(run / "words.json"), timeline)
        _write(out / "words.json", payload)
        report["files"]["words.json"] = {"words": len(payload["words"]), "dropped_word_ids": dropped}
    _write(out / "remap-report.json", report)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    a = sub.add_parser("analyze"); a.add_argument("--video", required=True); a.add_argument("--run", required=True)
    p = sub.add_parser("plan"); p.add_argument("--attempt", required=True); p.add_argument("--strength", choices=["normal", "gentle"], default="normal")
    p.add_argument("--filler-review"); p.add_argument("--no-fillers", action="store_true")
    v = sub.add_parser("preview"); v.add_argument("--attempt", required=True); v.add_argument("--count", type=int, default=3); v.add_argument("--length", type=float, default=60.0)
    r = sub.add_parser("render"); r.add_argument("--attempt", required=True); r.add_argument("--crf", type=int, default=16); r.add_argument("--skip-preview", action="store_true")
    args = parser.parse_args()
    {"analyze": cmd_analyze, "plan": cmd_plan, "preview": cmd_preview, "render": cmd_render}[args.command](args)


if __name__ == "__main__":
    main()
