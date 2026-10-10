# Private brand-pack policy

Brand packs separate personal/copyrighted images from distributable Skill code.

- `distribution_scope` must be `private-user-supplied`.
- JSON paths are relative to their declaring file and must resolve inside the pack root.
- The character must contain real transparent alpha pixels.
- Manifest and profile asset paths must resolve to the same files and SHA-256 values.
- ZIP installation rejects absolute/drive paths, path traversal, duplicate case-insensitive names, symlinks, encryption, executable extensions, excessive entry counts, and excessive expanded size.
- Installation uses a temporary sibling, verifies `checksums.sha256`, and promotes a new versioned directory. Existing versions remain recoverable.
- Public Skill archives must exclude private brand packs unless the user documents redistribution rights separately.
