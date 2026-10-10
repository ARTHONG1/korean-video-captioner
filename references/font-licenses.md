# Font license and portability

New caption, tip-card, and thumbnail outputs use Noto Sans KR files bundled with this Skill, both unmodified and taken from the same Noto CJK release (2.004, commit `523d033d6cb47f4a80c58a35753646f5c3608a78`):

- `assets/fonts/NotoSansKR-VF.ttf` (variable): tip cards, thumbnails, badges.
- `assets/fonts/caption/NotoSansKR-Bold.otf` (static Bold): burned-in captions. libass ignores the Bold flag on the variable font, so captions need a real bold face. It sits in its own folder so `fontsdir` exposes only this face.
- License: SIL Open Font License 1.1, `assets/fonts/OFL.txt` (identical to the upstream `Sans/LICENSE`).
- Hashes and source URLs: `assets/fonts/font-manifest.json`. `quick_validate.py` checks both hashes.

The OFL permits unmodified fonts to be bundled and redistributed with software when the copyright notice and license accompany each copy. The upstream copyright reserves the font name "Source" for modified versions, so never subset, instance, or otherwise modify these files inside the Skill; ship them byte-for-byte. Do not sell the fonts by themselves, remove the license, or relicense the font binaries. Do not switch captions to a font without a verified OFL or equivalent license file in the Skill.

Official sources:

- https://github.com/notofonts/noto-cjk (Sans/SubsetOTF/KR and Sans/Variable/TTF/Subset)
- https://github.com/google/fonts/tree/main/ofl/notosanskr
- https://openfontlicense.org/open-font-license-official-text/
