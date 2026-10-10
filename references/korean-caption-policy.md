# Korean caption policy

Keep meaning and speaking order. Remove only meaningless fillers, false starts, stutters, and immediate duplicate fragments. Correct spacing, spelling, punctuation, and an ASR error only when context makes it certain. Preserve protected tokens exactly. If unsure, mark review and keep raw text.

## Personal glossary

The glossary stores spellings the ASR keeps getting wrong: greetings, channel names, product names. It lives outside the Skill so personal names never ship with it.

```json
{
  "schema_version": 1,
  "entries": [
    {"canonical": "선생님 안녕하세요 AI선생님입니다", "variants": ["회원님 안녕하세요 AI 선생님입니다"]},
    {"canonical": "Playwright", "variants": ["플레이라이트", "playwright"]},
    {"canonical": "Kiro", "variants": ["kiro", "키로"]}
  ]
}
```

Matching ignores spacing and ASCII case; the longest variant wins. The validator accepts glossary replacements and ASCII case-only fixes (`kiro` → `Kiro`) but still rejects changed numbers, URLs, or dropped English identifiers. `build_corrected.py` applies the glossary even to cues whose proposal was rejected or missing, so fixed spellings never depend on a single proposal.

Add an entry when the user corrects the same term twice or names a fixed greeting or brand. Do not add guesses.

## Correction precedence

`build_corrected.py` reads `proposals/`, then `editor-proposals/`, then `resolution-proposals/`; the later directory wins for the same cue. `quality-report.json` counts rejected and missing proposals. More than 20% of cues kept raw sets `overall=NEEDS_REVIEW` and `publishable=false`.
