from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .brand_pack import BrandPack, load_brand_pack, resolve_pack_path
from .safe_zip import ALLOWED_SUFFIXES, SafeZipError, safe_extract, verify_checksums


@dataclass(frozen=True)
class InstalledBrandPack:
    path: Path
    pack: BrandPack


def default_brand_pack_root() -> Path:
    from .hostenv import brand_pack_root
    return brand_pack_root()


def discover_brand_pack(install_root: Path | None = None) -> BrandPack:
    root = Path(install_root) if install_root else default_brand_pack_root()
    pointer_path = root / "current.json"
    try:
        pointer = json.loads(pointer_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SafeZipError(f"invalid current brand-pack pointer: {pointer_path}") from exc
    if pointer.get("schema_version") != 1:
        raise SafeZipError("unsupported current brand-pack pointer schema_version")
    version = resolve_pack_path(root, str(pointer.get("brand_pack", "")), root)
    return load_brand_pack(version)


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o100644 << 16
    return info


def export_brand_pack(source_root: Path, destination: Path) -> Path:
    source_root = Path(source_root).resolve()
    load_brand_pack(source_root)
    for required in (source_root / "README.md", source_root / "legal" / "ASSET-RIGHTS.md"):
        if not required.is_file():
            raise SafeZipError(f"required private-pack document missing: {required.relative_to(source_root)}")
    destination = Path(destination)
    if destination.exists():
        raise SafeZipError(f"refusing to overwrite archive: {destination}")
    files = sorted(
        (path for path in source_root.rglob("*") if path.is_file() and path.name != "checksums.sha256"),
        key=lambda path: path.relative_to(source_root).as_posix(),
    )
    for path in files:
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise SafeZipError(f"disallowed private-pack extension: {path.name}")
    checksum_text = "".join(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(source_root).as_posix()}\n"
        for path in files
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    with zipfile.ZipFile(temporary, "x") as bundle:
        for path in files:
            name = path.relative_to(source_root).as_posix()
            bundle.writestr(_zip_info(name), path.read_bytes())
        bundle.writestr(_zip_info("checksums.sha256"), checksum_text.encode("utf-8"))
    temporary.replace(destination)
    return destination


def install_brand_pack(archive: Path, install_root: Path) -> InstalledBrandPack:
    install_root = Path(install_root).resolve()
    install_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".install-", dir=install_root))
    temporary.rmdir()
    try:
        safe_extract(Path(archive), temporary)
        verify_checksums(temporary)
        provisional = load_brand_pack(temporary)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
        destination = install_root / f"{provisional.identifier}-{stamp}"
        temporary.replace(destination)
        pack = load_brand_pack(destination)
        pointer = {"schema_version": 1, "brand_pack": destination.name}
        pointer_tmp = install_root / "current.json.tmp"
        pointer_tmp.write_text(json.dumps(pointer, ensure_ascii=False, indent=2), encoding="utf-8")
        pointer_tmp.replace(install_root / "current.json")
        return InstalledBrandPack(destination, pack)
    except Exception:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise
