"""Runs inside the runtime venv: re-transcribe one span for caption resolution."""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import transcribe_faster_whisper as tfw  # noqa: E402
from kvc import hostenv  # noqa: E402


def main() -> None:
    tfw.bootstrap_runtime()
    video, start, end, output, profile = sys.argv[1:6]
    from kvc.asr_runner import available_memory_bytes, transcribe_span

    engine = tfw.engine_choice(os.environ.get("KVC_ASR_ENGINE", "auto"))
    transcribe_span(
        int(start), int(end), Path(output),
        extract_audio=tfw.make_extractor(Path(video), hostenv.tool('ffmpeg')),
        transcribe_audio=tfw.transcriber_for(engine),
        requested_profile=profile, available=available_memory_bytes(), cores=os.cpu_count(),
    )
    print('RETRY_DONE', flush=True)


if __name__ == '__main__':
    main()
