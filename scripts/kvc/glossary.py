"""Personal caption glossary: fixed spellings the ASR keeps getting wrong.

The glossary lives outside the Skill (KVC_GLOSSARY or the default profile path)
so personal names never ship with the public Skill. Schema:

    {"schema_version": 1,
     "entries": [{"canonical": "클래스똑딱", "variants": ["클래스 똑딱"]}]}

A variant may be a single word or a whole phrase. Matching ignores spacing and
ASCII case; the longest variant wins.
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path


def default_glossary_path() -> Path:
    override = os.environ.get("KVC_GLOSSARY")
    if override:
        return Path(override)
    from .hostenv import profile_dir
    return profile_dir() / "glossary.json"


def _key(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text)).casefold()


@dataclass(frozen=True)
class Glossary:
    entries: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def canonicals(self) -> tuple[str, ...]:
        return tuple(canonical for canonical, _ in self.entries)

    def canonical_for(self, token: str) -> str | None:
        key = _key(token)
        for canonical, variants in self.entries:
            if key == _key(canonical) or any(key == _key(v) for v in variants):
                return canonical
        return None

    def apply(self, text: str) -> tuple[str, tuple[str, ...]]:
        """Replace known variants (spacing/case-insensitive) with the canonical form."""
        text = unicodedata.normalize("NFKC", text)
        patterns = []
        for canonical, variants in self.entries:
            for variant in variants:
                if _key(variant) and variant != canonical:
                    patterns.append((variant, canonical))
        patterns.sort(key=lambda item: len(_key(item[0])), reverse=True)
        hits: list[str] = []
        for variant, canonical in patterns:
            characters = [re.escape(ch) for ch in re.sub(r"\s+", "", unicodedata.normalize("NFKC", variant))]
            if not characters:
                continue
            pattern = re.compile(r"\s*".join(characters), re.IGNORECASE)
            text, count = pattern.subn(canonical, text)
            if count:
                hits.append(canonical)
        return re.sub(r"[ \t]{2,}", " ", text).strip(), tuple(dict.fromkeys(hits))


EMPTY = Glossary()


def load_glossary(path: Path | None = None) -> Glossary:
    path = Path(path) if path else default_glossary_path()
    if not path.is_file():
        return EMPTY
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or data.get("schema_version") != 1 or not isinstance(data.get("entries"), list):
        raise ValueError(f"invalid glossary schema: {path}")
    entries = []
    for item in data["entries"]:
        canonical = str(item.get("canonical", "")).strip()
        variants = tuple(str(v).strip() for v in item.get("variants", []) if str(v).strip())
        if not canonical:
            raise ValueError("glossary entry without canonical text")
        entries.append((canonical, variants))
    return Glossary(tuple(entries))
