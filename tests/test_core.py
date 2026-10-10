"""Fast checks that need no FFmpeg, model, or network:  python -m unittest discover -s tests"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from kvc import hostenv  # noqa: E402
from kvc.caption_style import CaptionStyle, layout_text, rounded_rect, split_cue, weighted_units  # noqa: E402
from kvc.compact_timeline import kept_count, src_to_out_seconds, talk_modulus  # noqa: E402
from kvc.publish_profile import DEFAULTS, load_publish_profile  # noqa: E402
from kvc.render import filter_path  # noqa: E402
from kvc.youtube_validation import chapter_times  # noqa: E402


class Captions(unittest.TestCase):
    def test_units(self):
        self.assertEqual(weighted_units("가나"), 2)
        self.assertEqual(weighted_units("AI 1"), 2)

    def test_layout_limits(self):
        text = "그래서 이런 식으로 만들어 보면 행사장에서도 오류 없이 사진을 바로 보낼 수 있을 것 같아요 정말 신기하죠"
        for lines in layout_text(text, 16, 2):
            self.assertLessEqual(len(lines), 2)
            for line in lines:
                self.assertLessEqual(weighted_units(line), 16)
                self.assertFalse(line.split()[-1] in {"이런", "그", "어떤"})

    def test_split_times_cover_cue(self):
        parts = split_cue(1000, 9000, "가나다라마바사아자차 카타파하 가나다라마바사 아자차카타파하 가나다라마 바사아자차카", CaptionStyle())
        self.assertEqual(parts[0][0], 1000)
        self.assertEqual(parts[-1][1], 9000)
        self.assertTrue(all(a < b for a, b, _ in parts))

    def test_metrics_real_pixels(self):
        m = CaptionStyle().metrics(1920, 1080)
        self.assertEqual(m["margin_v"], 162)
        self.assertEqual(m["font_size"], 81)

    def test_rounded_rect_closed(self):
        path = rounded_rect(400, 120, 24)
        self.assertTrue(path.startswith("m 24 0"))


class Timeline(unittest.TestCase):
    def test_talk_modulus(self):
        self.assertEqual(talk_modulus(1.1), 11)
        self.assertEqual(talk_modulus(1.0), 0)

    def test_kept_count(self):
        self.assertEqual(kept_count("talk", 10, 1, 11), 10)
        self.assertEqual(kept_count("talk", 11, 1, 11), 10)
        self.assertEqual(kept_count("ff", 17, 16, 11), 2)
        self.assertEqual(kept_count("cut", 99, 0, 11), 0)

    def test_mapping_with_intro(self):
        tl = {"fps": "60", "offset_frames": 120, "talk_modulus": 11, "pieces": [
            {"kind": "talk", "src_t0": 0.0, "src_t1": 10.0, "out0": 0, "nout": 546, "k": 1},
            {"kind": "ff", "src_t0": 10.0, "src_t1": 26.0, "out0": 546, "nout": 60, "k": 16}]}
        self.assertAlmostEqual(src_to_out_seconds(tl, 0.0), 2.0)
        self.assertAlmostEqual(src_to_out_seconds(tl, 26.0), (120 + 606) / 60)
        self.assertAlmostEqual(src_to_out_seconds(None, 5.0), 5.0)


import contextlib
import shutil

@contextlib.contextmanager
def _safe_temp():
    # Pick first writable directory among cwd, Documents/Codex, or system temp
    candidates = [
        Path.cwd(),
        Path.home() / "Documents" / "Codex",
    ]
    base = None
    for c in candidates:
        if c.is_dir() and os.access(str(c), os.W_OK):
            base = c / ".kvc_test_tmp"
            break
    if base is None:
        base = Path(tempfile.gettempdir()) / ".kvc_test_tmp"
    try:
        base.mkdir(parents=True, exist_ok=True)
        d = tempfile.mkdtemp(dir=str(base))
        try:
            yield d
        finally:
            shutil.rmtree(d, ignore_errors=True)
            if base.exists() and not any(base.iterdir()):
                shutil.rmtree(base, ignore_errors=True)
    except (PermissionError, OSError):
        # Fallback to direct tempdir if folder creation is restricted
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as td:
            yield td


class Profile(unittest.TestCase):
    def test_missing_profile_is_defaults(self):
        with _safe_temp() as d:
            p = load_publish_profile(Path(d) / "none.json")
            self.assertEqual(p["caption_style"]["preset"], DEFAULTS["caption_style"]["preset"])
            self.assertFalse(p["compact_edit"]["enabled"])

    def test_examples_are_valid(self):
        root = Path(__file__).resolve().parents[1] / "assets" / "profile-examples"
        for path in root.glob("*.json"):
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["schema_version"], 1)


class Host(unittest.TestCase):
    def test_overrides(self):
        with _safe_temp() as d:
            old = dict(os.environ)
            try:
                os.environ["KVC_RUNTIME_ROOT"] = d
                self.assertEqual(hostenv.runtime_root(), Path(d))
                self.assertTrue(str(hostenv.runtime_python()).startswith(d))
            finally:
                os.environ.clear()
                os.environ.update(old)

    def test_nfd_names(self):
        import unicodedata
        self.assertTrue(hostenv.same_name(unicodedata.normalize("NFD", "영상.mp4"), "영상.mp4"))

    def test_filter_path_relative_and_quoted(self):
        with _safe_temp() as d:
            try:
                target = Path(d) / "a b" / "x'y.ass"
                target.parent.mkdir()
                target.write_text("", encoding="utf-8")
                q = filter_path(target, Path(d))
                self.assertTrue(q.startswith("'") and ":" not in q)
            except PermissionError:
                target = Path(d) / "x'y.ass"
                target.write_text("", encoding="utf-8")
                q = filter_path(target, Path(d))
                self.assertTrue(q.startswith("'") and ":" not in q)

    def test_memory_reported(self):
        self.assertTrue(hostenv.available_memory_bytes() is None or hostenv.available_memory_bytes() > 0)


class Chapters(unittest.TestCase):
    def test_intro_chapter_and_pin(self):
        src = {"cues": [{"id": 1, "start_ms": 0, "out_start_ms": 40000}, {"id": 2, "start_ms": 1, "out_start_ms": 90000}],
               "chapter_settings": {"intro_ms": 32000, "intro_label": "미리보기"}}
        times = chapter_times(src, [{"title": "A", "source_cue_ids": [1]}, {"title": "B", "source_cue_ids": [2]}])
        self.assertEqual(times[0], (0, "미리보기"))
        src["chapter_settings"]["intro_ms"] = 0
        self.assertEqual(chapter_times(src, [{"title": "A", "source_cue_ids": [1]}])[0][0], 0)


if __name__ == "__main__":
    unittest.main()
