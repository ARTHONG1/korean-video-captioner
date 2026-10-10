from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

# More than this share of kept-raw cues means the captions need a human look.
MAX_WARNING_RATIO = 0.2


@dataclass(frozen=True)
class QualityWarning:
    cue_id: int
    code: str
    detail: str


@dataclass(frozen=True)
class QualityReport:
    overall: str
    publishable: bool
    counts: dict[str, int]
    warnings: tuple[QualityWarning, ...]

    @classmethod
    def from_warnings(cls, warnings: list[QualityWarning], total: int | None = None) -> "QualityReport":
        warning_tuple = tuple(warnings)
        counts: dict[str, int] = {"warnings": len(warning_tuple)}
        for warning in warning_tuple:
            counts[warning.code] = counts.get(warning.code, 0) + 1
        if total:
            counts["cues"] = total
        if not warning_tuple:
            return cls("PASS", True, counts, warning_tuple)
        if total and len(warning_tuple) / total > MAX_WARNING_RATIO:
            return cls("NEEDS_REVIEW", False, counts, warning_tuple)
        return cls("PASS_WITH_WARNINGS", True, counts, warning_tuple)


def write_quality_report(path: Path, report: QualityReport) -> None:
    path.write_text(json.dumps(asdict(report), ensure_ascii=False, indent=2), encoding="utf-8")

