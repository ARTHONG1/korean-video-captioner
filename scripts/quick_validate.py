import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_source(root: Path) -> list[str]:
    errors = []
    required = [
        'SKILL.md', 'agents/openai.yaml', 'references/korean-caption-policy.md',
        'references/output-contract.md', 'references/youtube-package-policy.md',
        'references/brand-pack-policy.md', 'references/font-licenses.md',
        'assets/fonts/NotoSansKR-VF.ttf', 'assets/fonts/OFL.txt',
        'assets/fonts/caption/NotoSansKR-Bold.otf',
        'assets/fonts/font-manifest.json', 'scripts/transcribe_faster_whisper.py',
        'scripts/video_captioner_adapter.py', 'scripts/export_brand_pack.py',
        'scripts/install_brand_pack.py', 'scripts/run_youtube_package.py',
        'scripts/verify_youtube_package.py',
        'references/caption-style.md', 'references/compact-edit.md', 'references/intro-promo.md',
        'scripts/render_captions.py', 'scripts/caption_preview.py', 'scripts/verify_caption_layout.py',
        'scripts/compact_edit.py', 'scripts/intro_join.py', 'scripts/kvc/caption_style.py',
        'scripts/kvc/publish_profile.py', 'scripts/kvc/compact_timeline.py', 'scripts/kvc/media_tools.py',
        'scripts/setup.py', 'scripts/run_background.py', 'scripts/asr_bench.py', 'scripts/build_release.py',
        'scripts/kvc/hostenv.py', 'references/setup.md', 'runtime-requirements/requirements.txt',
        'runtime-requirements/requirements-compatible.txt', 'runtime-requirements/requirements-apple-silicon.txt',
        'assets/profile-examples/glossary.example.json', 'assets/profile-examples/publish-profile.example.json', 'VERSION',
    ]
    for relative in required:
        if not (root / relative).is_file():
            errors.append(f'missing required file: {relative}')
    skill_path = root / 'SKILL.md'
    skill = skill_path.read_text(encoding='utf-8') if skill_path.is_file() else ''
    adapter_path = root / 'scripts' / 'video_captioner_adapter.py'
    adapter = adapter_path.read_text(encoding='utf-8') if adapter_path.is_file() else ''
    if 'transcribe_faster_whisper.py' not in skill:
        errors.append('canonical Faster-Whisper route missing from SKILL.md')
    if 'whisper-cpp' in adapter:
        errors.append('legacy whisper-cpp route present')
    if 'MarginV=35' in adapter:
        errors.append('legacy MarginV=35 present')
    if 'force_style' in adapter or 'render_captions' not in adapter:
        errors.append('adapter must render through kvc.render.render_captions (shared caption style), not force_style')
    render_path = root / 'scripts' / 'kvc' / 'render.py'
    if render_path.is_file() and r"replace(':', r'\\:')" in render_path.read_text(encoding='utf-8'):
        errors.append('legacy drive-colon escaping present in kvc/render.py')
    if 'Malgun Gothic' in adapter or 'malgun.ttf' in adapter.lower():
        errors.append('legacy Malgun Gothic production font present')
    for path in root.rglob('*'):
        if path.suffix.lower() not in {'.py', '.md', '.json', '.yaml', '.yml'} or not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except UnicodeError:
            continue
        if re.search(r'[A-Za-z]:\\Users\\[^\\\s]+', text) or re.search(r'/Users/(?!<)[A-Za-z0-9._-]+/', text):
            errors.append(f'machine-specific absolute path present: {path.relative_to(root)}')
    metadata_path = root / 'agents' / 'openai.yaml'
    if metadata_path.is_file():
        try:
            metadata = yaml.safe_load(metadata_path.read_text(encoding='utf-8'))
            prompt = metadata['interface']['default_prompt']
            if '$korean-video-captioner' not in prompt:
                errors.append('agents/openai.yaml default_prompt does not invoke the Skill')
        except Exception as exc:
            errors.append(f'invalid agents/openai.yaml: {exc}')
    manifest_path = root / 'assets' / 'fonts' / 'font-manifest.json'
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            font = manifest_path.parent / manifest['font_file']
            license_path = manifest_path.parent / manifest['license_file']
            if _sha256(font) != manifest['font_sha256'].lower():
                errors.append('bundled font SHA-256 mismatch')
            if _sha256(license_path) != manifest['license_sha256'].lower():
                errors.append('bundled font license SHA-256 mismatch')
            caption = manifest.get('caption_font')
            if not caption or _sha256(manifest_path.parent / caption['file']) != caption['sha256'].lower():
                errors.append('caption font missing or SHA-256 mismatch')
        except Exception as exc:
            errors.append(f'invalid bundled font manifest: {exc}')
    return errors


def validate_runtime(root: Path, runtime_root: Path) -> list[str]:
    errors = []
    sys.path.insert(0, str(root / 'scripts'))
    from kvc import hostenv
    os.environ.setdefault('KVC_RUNTIME_ROOT', str(runtime_root))
    python = hostenv.venv_python(runtime_root / '.venv')
    ffmpeg = hostenv.tool('ffmpeg')
    ffprobe = hostenv.tool('ffprobe')
    font = root / 'assets' / 'fonts' / 'NotoSansKR-VF.ttf'
    for label, path in [('python', python), ('ffmpeg', ffmpeg), ('ffprobe', ffprobe), ('font', font)]:
        if not path.is_file():
            errors.append(f'missing runtime {label}: {path}')
    if python.is_file():
        result = subprocess.run([str(python), '-c', 'import faster_whisper, PIL, fontTools; print(faster_whisper.__version__)'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        if result.returncode != 0:
            errors.append('runtime Python cannot import faster_whisper, Pillow, and fontTools')
    if ffmpeg.is_file():
        result = subprocess.run([str(ffmpeg), '-hide_banner', '-filters'], capture_output=True, text=True, encoding='utf-8', errors='replace')
        filters = result.stdout + result.stderr
        for name in ('subtitles', 'ass'):
            if name not in filters:
                errors.append(f'FFmpeg filter unavailable: {name}')
    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime-root', default=None, help='defaults to the platform runtime folder (kvc.hostenv.runtime_root)')
    parser.add_argument('--source-only', action='store_true')
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    errors = validate_source(root)
    if not args.source_only:
        if args.runtime_root is None:
            sys.path.insert(0, str(root / 'scripts'))
            from kvc import hostenv
            args.runtime_root = str(hostenv.runtime_root())
        errors.extend(validate_runtime(root, Path(args.runtime_root)))
    if errors:
        for error in errors:
            print(f'quick_validate: FAIL: {error}', file=sys.stderr)
        return 1
    print('quick_validate: PASS: portable Faster-Whisper, Noto Sans KR, and publishing package verified')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
