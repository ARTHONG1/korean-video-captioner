"""Operating-system differences in one place (Windows, macOS, Linux). Standard library only.

Folders (each can be overridden by an environment variable):
  runtime    KVC_RUNTIME_ROOT   Python venv, FFmpeg (Windows), selftest records
  profile    KVC_PROFILE_DIR    glossary.json, publish-profile.json (personal, never shipped)
  brand      KVC_BRAND_PACK_ROOT private book/character packs
Existing installs under ~/Documents/Codex keep working; new installs use the platform data folder
(%LOCALAPPDATA%, ~/Library/Application Support, ~/.local/share) so large files stay out of iCloud/OneDrive sync.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

APP = "korean-video-captioner"
IS_WINDOWS = os.name == "nt"
IS_MAC = sys.platform == "darwin"


def _legacy(*parts: str) -> Path:
    return Path.home().joinpath("Documents", "Codex", *parts)


def data_home() -> Path:
    if os.environ.get("KVC_HOME"):
        return Path(os.environ["KVC_HOME"])
    if IS_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP
    if IS_MAC:
        return Path.home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP


def runtime_root() -> Path:
    if os.environ.get("KVC_RUNTIME_ROOT"):
        return Path(os.environ["KVC_RUNTIME_ROOT"])
    legacy = _legacy("tools", "video-captioner-runtime")
    return legacy if legacy.is_dir() else data_home() / "runtime"


def profile_dir() -> Path:
    if os.environ.get("KVC_PROFILE_DIR"):
        return Path(os.environ["KVC_PROFILE_DIR"])
    legacy = _legacy("tools", "korean-video-captioner-profile")
    return legacy if legacy.is_dir() else data_home() / "profile"


def brand_pack_root() -> Path:
    if os.environ.get("KVC_BRAND_PACK_ROOT"):
        return Path(os.environ["KVC_BRAND_PACK_ROOT"])
    legacy = _legacy("assets", APP, "brand-packs")
    return legacy if legacy.is_dir() else data_home() / "brand-packs"


def venv_python(venv: Path) -> Path:
    venv = Path(venv)
    return venv / "Scripts" / "python.exe" if IS_WINDOWS else venv / "bin" / "python"


def runtime_python() -> Path:
    return venv_python(runtime_root() / ".venv")


def vision_python() -> Path:
    return venv_python(runtime_root() / ".venv-vision")


def in_venv(venv: Path) -> bool:
    try:
        return Path(sys.prefix).resolve() == Path(venv).resolve()
    except OSError:
        return False


def tool(name: str) -> Path:
    """ffmpeg/ffprobe: the runtime copy if present, else the one on PATH (Homebrew on macOS)."""
    exe = name + (".exe" if IS_WINDOWS else "")
    local = runtime_root() / "ffmpeg" / "bin" / exe
    if local.is_file():
        return local
    for extra in ("/opt/homebrew/bin", "/usr/local/bin") if IS_MAC else ():
        candidate = Path(extra) / name
        if candidate.is_file():
            return candidate
    found = shutil.which(name)
    return Path(found) if found else local


def available_memory_bytes() -> int | None:
    """Free physical memory (macOS counts free + inactive + speculative pages), or None."""
    try:
        if IS_WINDOWS:
            import ctypes

            class MemoryStatus(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

            status = MemoryStatus()
            status.dwLength = ctypes.sizeof(MemoryStatus)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return int(status.ullAvailPhys)
            return None
        if IS_MAC:
            out = subprocess.run(["vm_stat"], capture_output=True, text=True, check=True).stdout
            page = 4096
            first = out.splitlines()[0]
            if "page size of" in first:
                page = int(first.split("page size of")[1].split()[0])
            pages = {}
            for line in out.splitlines()[1:]:
                if ":" in line:
                    key, value = line.split(":", 1)
                    try:
                        pages[key.strip()] = int(value.strip().rstrip("."))
                    except ValueError:
                        pass
            free = sum(pages.get(k, 0) for k in ("Pages free", "Pages inactive", "Pages speculative", "Pages purgeable"))
            return free * page
        with open("/proc/meminfo", encoding="utf-8") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
        return int(os.sysconf("SC_AVPHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
    except Exception:
        return None


def pid_alive(pid: int) -> bool:
    """Check a PID without signalling it (os.kill terminates processes on Windows)."""
    if pid <= 0:
        return False
    if IS_WINDOWS:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return kernel32.GetLastError() == 5  # access denied means the process exists
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def low_priority_kwargs() -> dict:
    """subprocess.Popen kwargs that start a child below normal priority."""
    if IS_WINDOWS:
        return {"creationflags": 0x00004000}  # BELOW_NORMAL_PRIORITY_CLASS
    return {"preexec_fn": lambda: os.nice(10)}


def keep_awake(pid: int) -> subprocess.Popen | None:
    """macOS: keep the machine awake while pid runs (caffeinate exits with it)."""
    if IS_MAC and shutil.which("caffeinate"):
        return subprocess.Popen(["caffeinate", "-i", "-w", str(pid)])
    return None


def free_disk_bytes(path: Path) -> int | None:
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    try:
        return shutil.disk_usage(path).free
    except OSError:
        return None


def same_name(a: str, b: str) -> bool:
    """macOS stores Korean file names decomposed (NFD); compare in NFC."""
    return unicodedata.normalize("NFC", a).casefold() == unicodedata.normalize("NFC", b).casefold()


def find_file(folder: Path, name: str) -> Path | None:
    folder = Path(folder)
    direct = folder / name
    if direct.exists():
        return direct
    for child in folder.iterdir() if folder.is_dir() else ():
        if same_name(child.name, name):
            return child
    return None


def describe() -> dict:
    return {"os": platform.system(), "release": platform.release(), "machine": platform.machine(),
            "python": sys.version.split()[0], "apple_silicon": IS_MAC and platform.machine() == "arm64"}


def utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
