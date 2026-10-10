# korean-video-captioner

한국어 영상에 자연스럽게 교정한 자막을 넣고, 원하면 말 없는 구간 배속·공백 정리·홍보 인트로·유튜브 제목/설명/챕터/썸네일까지 만드는 AI 에이전트 스킬입니다.

## 설치

1. 압축을 풀어 `korean-video-captioner` 폴더를 스킬 폴더에 넣습니다. Codex는 `~/.codex/skills/`입니다.
2. 에이전트에게 "`$korean-video-captioner` 세팅해줘"라고 말합니다. 에이전트가 `scripts/setup.py`로 Python 환경, FFmpeg, 음성 인식 모델(약 3GB)을 설치하고 자가 테스트까지 합니다.
3. 맥에 Homebrew가 없으면 에이전트가 터미널에 붙여 넣을 명령 한 줄을 알려 줍니다. 맥 비밀번호가 필요한 단계라 이것만 직접 하면 됩니다.

필요한 것: macOS(Apple Silicon 권장) 또는 Windows 10/11, 여유 디스크 7GB, 여유 메모리 2.5GB 이상. Apple Silicon 맥에서는 자가 테스트를 통과하면 GPU 음성 인식 엔진을 자동으로 사용합니다.

## 사용

"`$korean-video-captioner` 동영상 폴더의 '강의.mp4' 작업해줘"처럼 말하면 됩니다. 채널 이름, 고정 인사말, 자주 틀리는 단어는 처음 사용할 때 에이전트가 개인 설정에 저장합니다. 개인 설정과 책·캐릭터 이미지는 스킬 밖에 저장되어 배포본에 섞이지 않습니다.

사용한 오픈소스와 라이선스는 `THIRD_PARTY_NOTICES.md`에 있습니다.
