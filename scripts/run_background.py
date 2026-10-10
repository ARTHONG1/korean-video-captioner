"""Start a long job in the background at low priority and return at once (Windows, macOS, Linux).

  run_background.py --log RUN/asr.log -- <python> transcribe_faster_whisper.py VIDEO RUN/raw.srt
Writes LOG (stdout+stderr) and LOG.pid. On macOS the Mac is kept awake (caffeinate) until the job exits.
"""
import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_spec = importlib.util.spec_from_file_location("kvc_hostenv", Path(__file__).resolve().parent / "kvc" / "hostenv.py")
H = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(H)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", required=True)
    ap.add_argument("cmd", nargs=argparse.REMAINDER)
    a = ap.parse_args()
    cmd = a.cmd[1:] if a.cmd and a.cmd[0] == "--" else a.cmd
    if not cmd:
        ap.error("command missing after --")
    log = Path(a.log)
    log.parent.mkdir(parents=True, exist_ok=True)
    out = open(log, "ab")
    kwargs = H.low_priority_kwargs()
    env = dict(__import__("os").environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8")
    if H.IS_WINDOWS:
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | 0x00000200 | 0x08000000  # new group, no window
    else:
        kwargs["start_new_session"] = True
    proc = subprocess.Popen(cmd, stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, env=env, **kwargs)
    H.keep_awake(proc.pid)
    Path(str(log) + ".pid").write_text(str(proc.pid), encoding="utf-8")
    print(json.dumps({"pid": proc.pid, "log": str(log)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
