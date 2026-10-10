from __future__ import annotations

import hashlib
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


class SafeZipError(ValueError):
    """Raised when an archive violates the private brand-pack contract."""


ALLOWED_SUFFIXES = {".json", ".png", ".md", ".txt", ".sha256"}
MAX_ENTRIES = 100
MAX_EXPANDED_BYTES = 100 * 1024 * 1024


def _safe_name(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SafeZipError(f"unsafe ZIP path: {name}")
    if ":" in path.parts[0]:
        raise SafeZipError(f"unsafe ZIP path: {name}")
    return path


def inspect_archive(archive: Path) -> list[zipfile.ZipInfo]:
    try:
        bundle = zipfile.ZipFile(archive)
    except Exception as exc:
        raise SafeZipError(f"invalid ZIP archive: {archive}") from exc
    with bundle:
        entries = bundle.infolist()
        if len(entries) > MAX_ENTRIES:
            raise SafeZipError(f"ZIP entry limit exceeded: {len(entries)}")
        seen: set[str] = set()
        expanded = 0
        for info in entries:
            path = _safe_name(info.filename)
            folded = path.as_posix().casefold()
            if folded in seen:
                raise SafeZipError(f"duplicate ZIP entry: {info.filename}")
            seen.add(folded)
            if info.flag_bits & 1:
                raise SafeZipError(f"encrypted ZIP entry is not allowed: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise SafeZipError(f"symlink ZIP entry is not allowed: {info.filename}")
            if not info.is_dir() and path.suffix.lower() not in ALLOWED_SUFFIXES:
                raise SafeZipError(f"disallowed ZIP extension: {info.filename}")
            expanded += info.file_size
        if expanded > MAX_EXPANDED_BYTES:
            raise SafeZipError(f"ZIP expanded size limit exceeded: {expanded}")
        return entries


def safe_extract(archive: Path, destination: Path) -> Path:
    entries = inspect_archive(Path(archive))
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(archive) as bundle:
        for info in entries:
            relative = Path(*_safe_name(info.filename).parts)
            target = destination / relative
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(info) as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)
    return destination


def verify_checksums(root: Path) -> None:
    root = Path(root).resolve()
    checksum_file = root / "checksums.sha256"
    if not checksum_file.is_file():
        raise SafeZipError("checksums.sha256 is missing")
    listed: set[Path] = set()
    for line in checksum_file.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            expected, raw = line.split("  ", 1)
        except ValueError as exc:
            raise SafeZipError(f"invalid checksum line: {line}") from exc
        target = root / Path(*_safe_name(raw).parts)
        if not target.is_file():
            raise SafeZipError(f"checksum target missing: {raw}")
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected.lower():
            raise SafeZipError(f"checksum mismatch: {raw}")
        listed.add(target.resolve())
    expected_files = {path.resolve() for path in root.rglob("*") if path.is_file() and path.name != "checksums.sha256"}
    if listed != expected_files:
        raise SafeZipError("checksums.sha256 does not cover every packaged file")
