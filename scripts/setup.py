#!/usr/bin/env python3
"""Self-setup for korean-video-captioner. Standard library only; runs on any system Python 3.8+.

  setup.py doctor [--json]                     what is ready and the exact next step
  setup.py install [--skip-model] [--with-vision]
  setup.py selftest [--no-asr]                 renders, edits, joins and transcribes generated media

The agent runs these itself (references/setup.md). Only steps that need a person (an admin password,
disk space, macOS privacy permission) are reported as user actions.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SCRIPTS = SKILL / "scripts"
REQ = SKILL / "runtime-requirements"
_spec = importlib.util.spec_from_file_location("kvc_hostenv", SCRIPTS / "kvc" / "hostenv.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)
H.utf8_stdio()

VERSION = (SKILL / "VERSION").read_text(encoding="utf-8").strip() if (SKILL / "VERSION").is_file() else "dev"
PY_MIN, PY_MAX, PY_TARGET = (3, 10), (3, 13), "3.12"
NEED_DISK = 7 * 1024**3
FW_REPO, MLX_REPO = "Systran/faster-whisper-large-v3", "mlx-community/whisper-large-v3-mlx"
KO_SCRIPT = ("안녕하세요. 오늘은 영상에 한국어 자막을 자동으로 넣는 방법을 알아보겠습니다. "
             "말소리를 인식해서 문장으로 바꾸고, 화면 아래에 깔끔하게 보여 줍니다.")
BTBN = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/"


def run(cmd, timeout=None, **kw):
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    return subprocess.run([str(c) for c in cmd], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          env=env, **kw)


def say(msg):
    print(msg, flush=True)


# ------------------------------------------------------------------ status checks
def py_version(exe) -> tuple | None:
    try:
        r = run(list(exe) + ["-c", "import sys;print('%d.%d' % sys.version_info[:2])"], timeout=60)
        return tuple(int(x) for x in r.stdout.strip().split(".")) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def venv_status() -> dict:
    py = H.runtime_python()
    if not py.is_file():
        return {"ok": False, "detail": f"runtime venv missing: {py}"}
    # Importing is not enough: decode a real WAV the way faster-whisper does (catches av/faster-whisper mismatches).
    code = ("import json, importlib.util as u, faster_whisper, numpy, PIL, fontTools, yaml, sys, av, wave, tempfile, os\n"
            "from faster_whisper.audio import decode_audio\n"
            "p = os.path.join(tempfile.mkdtemp(), 't.wav')\n"
            "w = wave.open(p, 'wb'); w.setnchannels(1); w.setsampwidth(2); w.setframerate(16000); w.writeframes(b'\\0\\0' * 16000); w.close()\n"
            "n = len(decode_audio(p))\n"
            "print(json.dumps({'python': '%d.%d' % sys.version_info[:2], 'faster_whisper': faster_whisper.__version__, 'av': av.__version__,"
            "'numpy': numpy.__version__, 'decode_samples': n, 'mlx_whisper': u.find_spec('mlx_whisper') is not None}))")
    r = run([py, "-c", code], timeout=300)
    if r.returncode != 0:
        return {"ok": False, "detail": "runtime packages missing or broken: " + r.stderr.strip()[-300:]}
    return {"ok": True, "detail": json.loads(r.stdout.strip().splitlines()[-1])}


def ffmpeg_status() -> dict:
    ff, fp = H.tool("ffmpeg"), H.tool("ffprobe")
    if not ff.is_file() or not fp.is_file():
        return {"ok": False, "detail": "ffmpeg/ffprobe not found", "path": str(ff)}
    first = run([ff, "-hide_banner", "-version"]).stdout.splitlines()[:1]
    version = first[0] if first else ""
    m = re.search(r"version n?(\d+)\.", version)
    major = int(m.group(1)) if m else (99 if re.search(r"version N-\d+", version) else 0)
    filters = run([ff, "-hide_banner", "-filters"]).stdout
    encoders = run([ff, "-hide_banner", "-encoders"]).stdout
    has = {"ass": bool(re.search(r"\sass\s", filters)), "subtitles": bool(re.search(r"\ssubtitles\s", filters)),
           "libx264": "libx264" in encoders, "version>=7": major >= 7}
    return {"ok": all(has.values()), "detail": {"path": str(ff), "version": version, **has}}


def hf_cache() -> Path:
    if os.environ.get("HF_HUB_CACHE"):
        return Path(os.environ["HF_HUB_CACHE"])
    return Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "hub"


def model_status() -> dict:
    def cached(repo, names):
        snaps = hf_cache() / ("models--" + repo.replace("/", "--")) / "snapshots"
        return any((s / n).exists() for s in snaps.glob("*") for n in names) if snaps.is_dir() else False
    fw = cached(FW_REPO, ["model.bin"])
    mlx = cached(MLX_REPO, ["weights.npz", "weights.safetensors", "model.safetensors"])
    return {"ok": fw, "detail": {"faster-whisper large-v3": fw, "mlx large-v3": mlx, "cache": str(hf_cache())}}


def fonts_status() -> dict:
    man = json.loads((SKILL / "assets" / "fonts" / "font-manifest.json").read_text(encoding="utf-8"))
    base = SKILL / "assets" / "fonts"
    items = [(man["font_file"], man["font_sha256"]), (man["license_file"], man["license_sha256"])]
    if man.get("caption_font"):
        items.append((man["caption_font"]["file"], man["caption_font"]["sha256"]))
    bad = [f for f, sha in items if not (base / f).is_file() or hashlib.sha256((base / f).read_bytes()).hexdigest() != sha.lower()]
    return {"ok": not bad, "detail": {"mismatch": bad}}


def selftest_status() -> dict:
    path = H.runtime_root() / "selftest.json"
    if not path.is_file():
        return {"ok": False, "detail": "selftest has not run on this computer"}
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = data.get("passed") and data.get("skill_version") == VERSION
    return {"ok": bool(ok), "detail": {"passed": data.get("passed"), "skill_version": data.get("skill_version"),
                                       "engine": data.get("engine"), "at": data.get("finished_at")}}


def doctor(as_json=False) -> dict:
    root = H.runtime_root()
    mem = H.available_memory_bytes()
    disk = H.free_disk_bytes(root)
    checks = {
        "runtime_venv": venv_status(),
        "ffmpeg": ffmpeg_status(),
        "fonts": fonts_status(),
        "whisper_model": model_status(),
        "selftest": selftest_status(),
    }
    actions = []
    if not checks["fonts"]["ok"]:
        actions.append({"who": "user", "why": "Skill files are damaged; reinstall the Skill from the release ZIP."})
    if not (checks["runtime_venv"]["ok"] and checks["ffmpeg"]["ok"] and checks["whisper_model"]["ok"]):
        actions.append({"who": "agent", "command": [sys.executable, str(Path(__file__).resolve()), "install"]})
    if not checks["selftest"]["ok"]:
        actions.append({"who": "agent", "command": [sys.executable, str(Path(__file__).resolve()), "selftest"]})
    report = {
        "skill_version": VERSION, "host": H.describe(), "runtime_root": str(root), "profile_dir": str(H.profile_dir()),
        "brand_pack_root": str(H.brand_pack_root()), "brand_pack_installed": (H.brand_pack_root() / "current.json").is_file(),
        "memory_available_gb": round(mem / 1024**3, 1) if mem else None, "disk_free_gb": round(disk / 1024**3, 1) if disk else None,
        "checks": checks, "ready": all(c["ok"] for c in checks.values()), "next_actions": actions,
    }
    if as_json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        say(f"korean-video-captioner {VERSION} on {report['host']['os']} {report['host']['machine']}")
        for name, c in checks.items():
            say(f"  [{'OK' if c['ok'] else '--'}] {name}: {c['detail'] if not c['ok'] else 'ready'}")
        say(f"  memory free {report['memory_available_gb']} GB, disk free {report['disk_free_gb']} GB")
        say("READY" if report["ready"] else "NOT READY -> " + json.dumps(actions, ensure_ascii=False))
    return report


# ------------------------------------------------------------------ install
def pick_python() -> list | None:
    candidates = [[sys.executable]]
    if H.IS_WINDOWS and shutil.which("py"):
        candidates += [["py", "-3.12"], ["py", "-3.13"], ["py", "-3.11"]]
    for name in ("python3.12", "python3.13", "python3.11", "python3.10", "python3", "python"):
        if shutil.which(name):
            candidates.append([shutil.which(name)])
    for exe in candidates:
        v = py_version(exe)
        if v and PY_MIN <= v <= PY_MAX:
            return exe
    return None


def uv_cmd() -> list:
    if shutil.which("uv"):
        return [shutil.which("uv")]
    if run([sys.executable, "-m", "uv", "--version"]).returncode == 0:
        return [sys.executable, "-m", "uv"]
    say("installing uv (user-level Python installer, no admin rights)")
    r = run([sys.executable, "-m", "pip", "install", "--user", "--quiet", "uv"])
    if r.returncode != 0:
        raise SystemExit("could not install uv: " + r.stderr[-500:])
    return [sys.executable, "-m", "uv"]


def make_venv(root: Path) -> dict:
    venv = root / ".venv"
    base = pick_python()
    if base:
        say(f"creating runtime venv with {' '.join(base)}")
        r = run(base + ["-m", "venv", str(venv)])
        if r.returncode != 0:
            raise SystemExit("venv failed: " + r.stderr[-800:])
        py = H.venv_python(venv)
        run([py, "-m", "pip", "install", "--quiet", "--upgrade", "pip"])
        installer = [str(py), "-m", "pip", "install", "--quiet"]
        how = "venv:" + " ".join(base)
    else:
        uv = uv_cmd()
        say(f"no Python {PY_MIN[0]}.{PY_MIN[1]}-{PY_MAX[0]}.{PY_MAX[1]} found; uv installs Python {PY_TARGET}")
        r = run(uv + ["venv", "--seed", "--python", PY_TARGET, str(venv)])
        if r.returncode != 0:
            raise SystemExit("uv venv failed: " + r.stderr[-800:])
        py = H.venv_python(venv)
        installer = uv + ["pip", "install", "--python", str(py)]
        how = "uv"
    used = "requirements.txt"
    say("installing Python packages (first time: a few minutes)")
    r = run(installer + ["-r", str(REQ / "requirements.txt")])
    if r.returncode != 0:
        say("exact versions unavailable here; installing compatible versions")
        used = "requirements-compatible.txt"
        r = run(installer + ["-r", str(REQ / used)])
        if r.returncode != 0:
            raise SystemExit("package install failed: " + r.stderr[-1500:])
    mlx = None
    if H.describe()["apple_silicon"]:
        say("installing the Apple Silicon GPU engine (mlx-whisper)")
        r = run(installer + ["-r", str(REQ / "requirements-apple-silicon.txt")])
        mlx = r.returncode == 0
        if not mlx:
            say("mlx-whisper install failed; the CPU engine will be used (" + r.stderr.strip()[-200:] + ")")
    return {"how": how, "requirements": used, "mlx_whisper": mlx}


def _download(url: str, dest: Path) -> Path:
    say(f"downloading {url}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh, 1024 * 1024)
    tmp.replace(dest)
    return dest


def install_ffmpeg(root: Path) -> dict:
    if H.IS_MAC:
        brew = shutil.which("brew") or next((p for p in ("/opt/homebrew/bin/brew", "/usr/local/bin/brew") if Path(p).is_file()), None)
        if not brew:
            return {"ok": False, "user_action": "Homebrew is needed once for FFmpeg. Ask the user to paste this in Terminal and enter "
                    "their Mac password: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\""}
        say("installing FFmpeg with Homebrew (several minutes the first time)")
        r = run([brew, "install", "ffmpeg"], timeout=3600)
        return {"ok": r.returncode == 0, "how": "homebrew", "log": r.stderr[-500:]}
    name = "ffmpeg-master-latest-win64-gpl.zip" if H.IS_WINDOWS else "ffmpeg-master-latest-linux64-gpl.tar.xz"
    downloads = root / "downloads"
    archive = _download(BTBN + name, downloads / name)
    sums = _download(BTBN + "checksums.sha256", downloads / "checksums.sha256").read_text(encoding="utf-8")
    expected = next((line.split()[0] for line in sums.splitlines() if line.strip().endswith(name)), None)
    actual = hashlib.sha256(archive.read_bytes()).hexdigest()
    if not expected or expected.lower() != actual:
        archive.unlink(missing_ok=True)
        raise SystemExit(f"FFmpeg download checksum mismatch ({actual} vs {expected})")
    bindir = root / "ffmpeg" / "bin"
    bindir.mkdir(parents=True, exist_ok=True)
    wanted = {"ffmpeg.exe", "ffprobe.exe"} if H.IS_WINDOWS else {"ffmpeg", "ffprobe"}
    if name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for member in z.namelist():
                base = member.rsplit("/", 1)[-1]
                if base in wanted and "/bin/" in member:
                    (bindir / base).write_bytes(z.read(member))
    else:
        with tarfile.open(archive) as t:
            for member in t.getmembers():
                base = member.name.rsplit("/", 1)[-1]
                if base in wanted and "/bin/" in member.name:
                    (bindir / base).write_bytes(t.extractfile(member).read())
                    os.chmod(bindir / base, 0o755)
    archive.unlink(missing_ok=True)
    return {"ok": True, "how": "BtbN " + name, "sha256": actual}


def seed_profile() -> list:
    target = H.profile_dir()
    target.mkdir(parents=True, exist_ok=True)
    made = []
    for example in (SKILL / "assets" / "profile-examples").glob("*.example.json"):
        dest = target / example.name.replace(".example", "")
        if not dest.exists():
            shutil.copy2(example, dest)
            made.append(str(dest))
    return made


def install(args) -> int:
    root = H.runtime_root()
    root.mkdir(parents=True, exist_ok=True)
    disk = H.free_disk_bytes(root)
    if disk is not None and disk < NEED_DISK:
        say(f"USER_ACTION: free at least {NEED_DISK / 1024**3:.0f} GB on the disk holding {root} (now {disk / 1024**3:.1f} GB)")
        return 4
    record = {"skill_version": VERSION, "host": H.describe(), "started_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    if not venv_status()["ok"]:
        record["venv"] = make_venv(root)
        if not venv_status()["ok"]:
            say("runtime still broken after install: " + str(venv_status()["detail"]))
            return 2
    elif H.describe()["apple_silicon"] and not venv_status()["detail"].get("mlx_whisper"):
        py = H.runtime_python()
        r = run([py, "-m", "pip", "install", "--quiet", "-r", str(REQ / "requirements-apple-silicon.txt")])
        record["mlx_whisper"] = r.returncode == 0
    if not ffmpeg_status()["ok"]:
        result = install_ffmpeg(root)
        record["ffmpeg"] = result
        if result.get("user_action"):
            say("USER_ACTION: " + result["user_action"])
            (root / "install.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
            return 4
        if not ffmpeg_status()["ok"]:
            say("FFmpeg is installed but lacks a required feature: " + json.dumps(ffmpeg_status()["detail"], ensure_ascii=False))
            return 2
    py = H.runtime_python()
    if not args.skip_model:
        say("downloading the Whisper large-v3 model (about 3 GB, first time only)")
        r = run([py, "-c", "from faster_whisper import download_model; print(download_model('large-v3'))"])
        if r.returncode != 0:
            say("model download failed: " + r.stderr[-800:])
            return 2
        if H.describe()["apple_silicon"] and venv_status()["detail"].get("mlx_whisper"):
            r = run([py, "-c", f"from huggingface_hub import snapshot_download; print(snapshot_download('{MLX_REPO}'))"])
            record["mlx_model"] = r.returncode == 0
    if args.with_vision:
        r = run([py, str(SCRIPTS / "bootstrap_vision_runtime.py"), "--target", str(root / ".venv-vision")])
        record["vision"] = r.returncode == 0
    record["profile_created"] = seed_profile()
    record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (root / "install.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    report = doctor()
    return 0 if all(report["checks"][k]["ok"] for k in ("runtime_venv", "ffmpeg", "fonts")) else 2


# ------------------------------------------------------------------ selftest
def korean_speech(work: Path) -> Path | None:
    aiff = work / "speech-src"
    try:
        if H.IS_MAC and shutil.which("say"):
            voices = run(["say", "-v", "?"]).stdout
            voice = next((line.split()[0] for line in voices.splitlines() if "ko_KR" in line), None)
            if voice:
                run(["say", "-v", voice, "-o", str(aiff.with_suffix(".aiff")), KO_SCRIPT], timeout=120)
                return aiff.with_suffix(".aiff") if aiff.with_suffix(".aiff").is_file() else None
        if H.IS_WINDOWS:
            ps = ("Add-Type -AssemblyName System.Speech; $s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                  "$v = $s.GetInstalledVoices() | ? { $_.VoiceInfo.Culture.Name -eq 'ko-KR' } | select -First 1; "
                  "if ($v) { $s.SelectVoice($v.VoiceInfo.Name); $s.SetOutputToWaveFile('" + str(aiff.with_suffix(".wav")) + "'); "
                  "$s.Speak('" + KO_SCRIPT + "'); $s.Dispose(); 'OK' }")
            r = run(["powershell", "-NoProfile", "-Command", ps], timeout=120)
            return aiff.with_suffix(".wav") if "OK" in r.stdout and aiff.with_suffix(".wav").is_file() else None
    except (OSError, subprocess.SubprocessError):
        return None
    return None


def similarity(a: str, b: str) -> float:
    norm = lambda s: re.sub(r"[\s.,!?]", "", s)  # noqa: E731
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def selftest(args) -> int:
    root = H.runtime_root()
    py = H.runtime_python()
    if not venv_status()["ok"] or not ffmpeg_status()["ok"]:
        say("run setup.py install first")
        return 2
    ff = H.tool("ffmpeg")
    work = root / "selftest" / time.strftime("%Y%m%d-%H%M%S")
    work.mkdir(parents=True)
    steps, engine = {}, {"engine": "faster-whisper", "validated": False}

    def step(name, cmd, timeout=1800):
        started = time.time()
        r = run(cmd, timeout=timeout, cwd=str(work))
        steps[name] = {"ok": r.returncode == 0, "seconds": round(time.time() - started, 1)}
        if r.returncode != 0:
            steps[name]["error"] = (r.stderr or r.stdout)[-800:]
        say(f"  {'PASS' if r.returncode == 0 else 'FAIL'} {name} ({steps[name]['seconds']} s)")
        return r

    say(f"selftest in {work}")
    speech = korean_speech(work)
    if speech:
        step("speech_wav", [ff, "-y", "-v", "error", "-i", speech, "-ac", "1", "-ar", "16000", work / "speech.wav"])
        vad = ("import sys, json; from faster_whisper.audio import decode_audio; from faster_whisper.vad import VadOptions, "
               "get_speech_timestamps; a = decode_audio(sys.argv[1]); s = get_speech_timestamps(a, VadOptions(min_silence_duration_ms=500)); "
               "print(json.dumps({'seconds': len(a) / 16000, 'speech_regions': len(s)})); sys.exit(0 if s else 3)")
        step("audio_decode_and_vad", [py, "-c", vad, work / "speech.wav"])
        audio_in = ["-i", str(work / "speech.wav")]
    else:
        audio_in = ["-f", "lavfi", "-i", "sine=f=330:d=9"]
    step("make_video", [ff, "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=1280x720:r=30:d=40"] + audio_in +
         ["-af", "apad=whole_dur=40", "-t", "40", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", work / "test.mp4"])
    srt = ("1\n00:00:00,500 --> 00:00:04,500\n안녕하세요. 오늘은 영상에 한국어 자막을\n\n"
           "2\n00:00:04,600 --> 00:00:09,000\n자동으로 넣는 방법을 알아보겠습니다. Kiro와 AI 도구 2개를 함께 씁니다.\n\n")
    (work / "test.srt").write_text(srt, encoding="utf-8")
    step("render_captions", [py, SCRIPTS / "render_captions.py", "--video", work / "test.mp4", "--srt", work / "test.srt",
                             "--out", work / "captioned.mp4"])
    step("caption_layout", [py, SCRIPTS / "verify_caption_layout.py", "--ass", work / "captioned.captions.ass",
                            "--out", work / "caption-layout-verify.json"])
    r = step("compact_detect", [py, SCRIPTS / "compact_edit.py", "detect", "--video", work / "captioned.mp4", "--run", work,
                                "--srt", work / "test.srt"])
    m = re.search(r'"attempt": "([^"]+)"', r.stdout)
    if m:
        attempt = Path(json.loads('"' + m.group(1) + '"'))
        step("compact_approve", [py, SCRIPTS / "compact_edit.py", "approve", "--attempt", attempt, "--note", "selftest media"])
        step("compact_build", [py, SCRIPTS / "compact_edit.py", "build", "--attempt", attempt])
        step("make_intro", [ff, "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=0x1a2240:s=1280x720:r=30:d=3", "-f", "lavfi",
                            "-i", "sine=f=523:d=3", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", work / "intro.mp4"])
        step("intro_join", [py, SCRIPTS / "intro_join.py", "--intro", work / "intro.mp4", "--main", attempt / "compact.mp4",
                            "--main-audio", attempt / "compact-audio.wav", "--srt", attempt / "publication-compact.srt",
                            "--out", work / "final-with-intro.mp4"])
    else:
        steps["compact_detect"]["ok"] = False
    if not args.no_asr:
        mem = H.available_memory_bytes()
        if not model_status()["ok"]:
            steps["asr"] = {"ok": False, "error": "model not downloaded; run setup.py install"}
        elif mem is not None and mem < int(2.5 * 1024**3):
            steps["asr"] = {"ok": None, "skipped": f"only {mem / 1024**3:.1f} GB free memory; rerun selftest after closing apps"}
        else:
            wav = work / "speech.wav" if speech else work / "tone.wav"
            if not speech:
                run([ff, "-y", "-v", "error", "-f", "lavfi", "-i", "sine=f=330:d=5", "-ac", "1", "-ar", "16000", wav])
            r = step("asr_faster_whisper", [py, SCRIPTS / "asr_bench.py", "--wav", wav, "--engine", "faster-whisper"], timeout=3600)
            fw = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
            if fw and speech:
                fw["similarity"] = similarity(fw["text"], KO_SCRIPT)
                steps["asr_faster_whisper"]["ok"] = fw["similarity"] >= 0.75
            steps.setdefault("asr_faster_whisper", {})["result"] = fw
            if H.describe()["apple_silicon"] and venv_status()["detail"].get("mlx_whisper") and speech:
                r = step("asr_mlx", [py, SCRIPTS / "asr_bench.py", "--wav", wav, "--engine", "mlx"], timeout=3600)
                mx = json.loads(r.stdout.strip().splitlines()[-1]) if r.returncode == 0 else None
                if mx:
                    mx["similarity"] = similarity(mx["text"], KO_SCRIPT)
                    steps["asr_mlx"]["result"] = mx
                    good = fw and mx["similarity"] >= 0.75 and mx["similarity"] >= fw["similarity"] - 0.05
                    faster = fw and mx["seconds"] * 1.2 < fw["seconds"]
                    engine = {"engine": "mlx" if good and faster else "faster-whisper", "validated": bool(good and faster),
                              "similarity": {"faster-whisper": fw and fw["similarity"], "mlx": mx["similarity"]},
                              "seconds": {"faster-whisper": fw and fw["seconds"], "mlx": mx["seconds"]}}
                    steps["asr_mlx"]["ok"] = True  # a slower or weaker mlx is not a failure; it is simply not selected
            elif not speech:
                engine["note"] = "no Korean system voice for an accuracy check; the CPU reference engine stays selected"
    engine["measured_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    (root / "engine.json").write_text(json.dumps(engine, ensure_ascii=False, indent=2), encoding="utf-8")
    required = [k for k in steps if k not in ("asr",) and not k.startswith("asr_mlx")]
    passed = all(steps[k].get("ok") for k in required) and steps.get("asr", {}).get("ok", True) is not False
    record = {"skill_version": VERSION, "host": H.describe(), "passed": passed, "engine": engine, "steps": steps,
              "korean_speech_sample": bool(speech), "work": str(work), "finished_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (root / "selftest.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    say(("SELFTEST PASS" if passed else "SELFTEST FAIL") + f"  engine={engine['engine']}")
    return 0 if passed else 2


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("doctor")
    d.add_argument("--json", action="store_true")
    i = sub.add_parser("install")
    i.add_argument("--skip-model", action="store_true")
    i.add_argument("--with-vision", action="store_true")
    t = sub.add_parser("selftest")
    t.add_argument("--no-asr", action="store_true")
    a = ap.parse_args()
    if a.cmd == "doctor":
        return 0 if doctor(a.json)["ready"] else 1
    if a.cmd == "install":
        return install(a)
    return selftest(a)


if __name__ == "__main__":
    raise SystemExit(main())
