from dataclasses import dataclass
from pathlib import Path

from . import hostenv


def _font_path() -> Path:
    try:
        from .font import bundled_font
        return bundled_font().path
    except ModuleNotFoundError:
        return Path(__file__).parents[2] / 'assets' / 'fonts' / 'NotoSansKR-VF.ttf'


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    python: Path
    ffmpeg: Path
    ffprobe: Path
    font: Path

    @property
    def vision_python(self) -> Path:
        return hostenv.vision_python()

    @property
    def yunet_model(self) -> Path:
        return Path(__file__).parents[2] / 'assets' / 'models' / 'face_detection_yunet_2023mar.onnx'

    @classmethod
    def discover(cls):
        return cls(hostenv.runtime_root(), hostenv.runtime_python(), hostenv.tool('ffmpeg'), hostenv.tool('ffprobe'), _font_path())
