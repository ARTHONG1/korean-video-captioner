"""Build a distributable copy of the Skill (no personal data) and a ZIP.

  build_release.py --out DIST_DIR
Copies the Skill without caches, refuses personal or machine-specific content, writes RELEASE-MANIFEST.json
(SHA-256 of every file) and DIST_DIR/korean-video-captioner-VERSION.zip. Never touches the source Skill.
"""
import argparse
import hashlib
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
SKIP_DIRS = {"__pycache__", ".pytest_cache", "dist", ".git"}
SKIP_SUFFIX = {".pyc", ".tmp", ".part", ".log"}
ALLOWED_LARGE = {"NotoSansKR-VF.ttf", "NotoSansKR-Bold.otf"}
PRIVATE_PATTERNS = [re.compile(p) for p in (r"[A-Za-z]:\\Users\\[^\\\s]+", r"/Users/(?!<)[A-Za-z0-9._-]+/", r"sk-[A-Za-z0-9]{20,}",
                                             r"hong-chan-woo")]
PRIVATE_FILES = {"brand-pack.json", "glossary.json", "publish-profile.json", "current.json"}
IMAGE_SUFFIX = {".png", ".jpg", ".jpeg", ".webp"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--public", action="store_true", help="public release: a LICENSE file is required")
    ap.add_argument("--clean", action="store_true", help="overwrite existing output folder if present")
    a = ap.parse_args()
    version = (SKILL / "VERSION").read_text(encoding="utf-8").strip()
    out = Path(a.out).resolve()
    stage = out / f"korean-video-captioner-{version}" / "korean-video-captioner"
    if stage.parent.exists():
        if a.clean:
            shutil.rmtree(stage.parent)
        else:
            raise SystemExit(f"refusing to overwrite {stage.parent} (use --clean to overwrite)")
    problems, files = [], []
    for path in sorted(SKILL.rglob("*")):
        rel = path.relative_to(SKILL)
        if any(part in SKIP_DIRS for part in rel.parts) or path.is_dir() or path.suffix in SKIP_SUFFIX:
            continue
        if path.stat().st_size > 2 * 1024**2 and path.name not in ALLOWED_LARGE:
            problems.append(f"unexpected large file: {rel}")
        if path.name in PRIVATE_FILES or path.suffix.lower() in IMAGE_SUFFIX:
            problems.append(f"personal data file (brand pack, profile, or image) inside the Skill: {rel}")
        if path.suffix in {".py", ".md", ".json", ".yaml", ".yml", ".txt"} and rel.parts[0] != "tests":
            text = path.read_text(encoding="utf-8", errors="replace")
            for pattern in PRIVATE_PATTERNS:
                if pattern.search(text) and not (rel.name == "build_release.py"):
                    problems.append(f"personal or machine-specific text ({pattern.pattern}) in {rel}")
        files.append((path, rel))
    for need in ("THIRD_PARTY_NOTICES.md", "README.md", "SKILL.md", "VERSION") + (("LICENSE",) if a.public else ()):
        if not (SKILL / need).is_file():
            problems.append(f"missing {need}")
    if problems:
        print("\n".join("RELEASE BLOCKED: " + p for p in problems), file=sys.stderr)
        return 2
    license_note = "see LICENSE" if (SKILL / "LICENSE").is_file() else "no license chosen yet: share privately only"
    manifest = {"name": "korean-video-captioner", "version": version, "license": license_note, "files": {}}
    for path, rel in files:
        dest = stage / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)
        manifest["files"][rel.as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (stage / "RELEASE-MANIFEST.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    archive = out / f"korean-video-captioner-{version}.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(stage.rglob("*")):
            if path.is_file():
                z.write(path, Path("korean-video-captioner") / path.relative_to(stage))
    print(json.dumps({"folder": str(stage), "zip": str(archive), "files": len(files) + 1, "zip_mb": round(archive.stat().st_size / 1e6, 1)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
