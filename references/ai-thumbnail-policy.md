# AI reference thumbnail policy

The AI reference mode is enabled only for an explicit user request or explicit `$korean-video-captioner` `full-publish` invocation. It sends the installed private book and transparent character images to Codex built-in image generation as reference inputs. The Skill must disclose this behavior in installation documentation.

Use case is `ads-marketing`; output is a 1280x720 landscape YouTube thumbnail. The prompt must identify Image 1 as the exact book reference and Image 2 as the exact character reference, include the validated Korean headline verbatim, and prohibit extra text, gibberish, watermarks, unrelated logos, unrelated subjects, and clipping.

Create three variants: `book-led`, `character-led`, and `balanced`. Generate each separately. Preserve raw output, normalize a usable landscape result to 1280x720 RGB, and record SHA-256, prompt hash, reference hashes, variant, and backend. Never overwrite a candidate or prior final thumbnail.

When the user asks for a specific visual from the video in the thumbnail (for example the app screen the video is about), pass a clean frame crop with `run_ai_thumbnail.py prepare --scene-image FRAME.png --scene-description "..."`. It becomes Image 3 after the book and character, the prompts place it between them, and the request records its hash. Use only frames from the user's own video and credit any third-party project in the description. Without such a request, keep the two references only.

The current Codex must visually inspect every candidate. A candidate passes only when both references are recognizable, the exact headline appears once and is legible, no extra gibberish/text is visible, no key subject is clipped, no watermark/unrelated logo exists, and the lower-right duration safe zone is nonessential. Score click appeal 30, reference fidelity 25, headline readability 25, cleanliness 10, and composition 10. Select the highest passing candidate at score 80 or higher.

Python validates the review structure, candidate provenance, hashes, dimensions, call limit, and selection rule. It does not claim to deterministically prove identity fidelity. If all candidates fail, preserve the attempt and report review failure; do not silently replace it with deterministic output.
