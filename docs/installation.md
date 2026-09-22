# 설치와 웹 관리

처음 설치한다면 [README의 빠른 설치](../README.md#빠른-설치--docker)부터 시작하세요. 필요한 RAM·디스크·지원 운영체제는 [실행 환경과 저장 공간](hardware-requirements.md)에 정리했습니다.

Windows 10/11 x64에서 Docker 없이 설치하려면 프로젝트 루트의 **`Install-Windows.cmd`**를 더블클릭하세요. 필요한 도구 준비와 앱 설치를 함께 진행합니다. [Windows 전용 안내](windows.md)에 수동 설치, 실행과 문제 해결을 정리했습니다.

## Docker 설치

Git과 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 또는 Linux Docker Engine + Compose를 준비합니다.

```sh
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
docker compose up --build -d
docker compose ps
```

이미지에는 Python 3.12, FFmpeg, STT/RAG 실행 환경과 빌드된 웹 화면이 포함됩니다. 음성·임베딩 모델은 첫 실행 후 웹에서 설치합니다. 기본 구성은 Linux CPU 실행이며 Mac의 MLX나 NVIDIA GPU를 사용하지 않습니다.

[http://127.0.0.1:8765](http://127.0.0.1:8765)를 열면 방문자로 접속합니다. 관리자 키는 아래 명령으로 확인하고 화면 상단 **관리자 로그인**에 입력합니다.

```sh
docker compose exec meetingbot cat /data/stt/local-token
```

`meetingbot-data` 볼륨의 `/data/stt`에 전사·권한·음성 모델을, `/data/rag`에 문서·색인·임베딩 모델을 저장합니다. 이 볼륨은 컨테이너를 재생성해도 유지됩니다. 기본 웹 포트는 호스트의 `127.0.0.1:8765`에만 열립니다.

```sh
docker compose stop
docker compose start
docker compose logs --tail=100 meetingbot
```

애플리케이션 상세 로그는 볼륨 안 `/data/stt/logs/backend.log`와 `/data/stt/logs/rag.log`에 있습니다. `docker compose down`은 컨테이너를 제거하고 데이터를 유지하지만 **`docker compose down -v`는 데이터 볼륨도 삭제합니다.**

## 네이티브 설치

지원 대상으로 구성한 환경은 Windows x64, macOS 14+ Apple Silicon, Linux x86_64/ARM64입니다. 현재 잠금 파일은 Intel Mac용 PyTorch를 포함하지 않으므로 Intel Mac에서는 Docker를 사용하세요.

필수 도구는 Git, 설치 스크립트를 실행할 Python 3.11/3.12, Node.js 22와 npm, FFmpeg와 ffprobe입니다. 각 실행 파일이 PATH에서 검색되어야 합니다. Apple Silicon + Homebrew에서는 다음으로 준비할 수 있습니다.

```sh
brew install python@3.12 node@22 ffmpeg
```

Homebrew가 안내하는 Node.js 22 PATH 설정을 적용한 뒤 새 터미널에서 `node --version`, `npm --version`, `ffmpeg -version`, `ffprobe -version`을 확인하세요. Windows는 [Python](https://www.python.org/downloads/windows/), [Node.js](https://nodejs.org/en/download), [FFmpeg](https://ffmpeg.org/download.html)를 준비합니다. Linux는 사용하는 배포판의 패키지 관리자로 준비하세요.

```sh
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
python3 scripts/install.py
```

Windows에서는 `py -3.12 scripts/install.py`를 사용합니다. 설치만 하고 실행하지 않으려면 `--no-launch`를 붙입니다. uv가 없으면 프로젝트 전용 `.bootstrap/`에 설치하고, Python 3.12와 잠금 파일에 맞는 두 가상 환경, 웹 화면을 준비합니다. 시스템 Python 패키지를 변경하지 않습니다.

설치 후 생성되는 `Meetingbot.command`(macOS), `Meetingbot.cmd`(Windows), `./Meetingbot.sh`(Linux)를 열면 STT와 RAG가 함께 시작되고 브라우저가 관리자 세션으로 열립니다. 창을 닫거나 Ctrl+C를 누르면 해당 런처가 시작한 서비스가 종료됩니다. 자동 로그인 시작은 공통 런처에 포함되지 않습니다.

포트 8765/8766을 다른 설치가 쓰면 실행을 중단합니다. 같은 설치의 서비스는 인증을 확인해 재사용하며, 하나만 실행 중이면 부족한 서비스만 시작합니다. 기존 macOS LaunchAgent 설치는 [기존 서비스 운영 안내](rag/installation.md)를 참고하세요.

## 첫 모델 설치와 웹 설정

1. **설정 및 관리 → 음성 인식**에서 지원 엔진의 **Small → 설치**를 누릅니다. Apple Silicon 네이티브는 MLX, Windows/Linux/Docker는 Faster Whisper CPU를 사용합니다.
2. 설치가 끝나면 **사용하기**를 눌러 워커에 적용합니다. 진행 중인 전사가 없어야 변경할 수 있습니다.
3. **자료 검색** 설정에서 임베딩 모델을 설치합니다. 워크스페이스를 만들고 문서를 올린 뒤 색인 완료를 기다립니다.
4. **AI 연결**에서 OpenAI 호환 서버·모델을 설정합니다. AI 답변과 회의 도우미를 사용할 워크스페이스에 한해 외부 전송을 허용합니다.

음성 엔진은 데이터 폴더의 독립된 환경에 설치됩니다. 모델 설치 이력과 다운로드 revision은 manifest에 저장되며 실패한 적용은 이전 워커를 유지합니다. 다운로드는 PyPI/Hugging Face에 접속하지만 준비된 전사 모델은 로컬 경로에서 오프라인으로 사용합니다.

임베딩 청크 크기·겹침·검색 결과 수는 웹에서 바꿀 수 있으며 청킹 변경 후 기존 자료는 재색인이 필요합니다. AI 연결은 별도 서버에 대한 연결 설정이며 로컬 LLM 가중치를 설치하는 기능은 아닙니다.

## 화자 분석 모델 (선택)

Community-1은 웹 음성 카탈로그와 별도로 준비합니다. [모델 페이지](https://huggingface.co/pyannote/speaker-diarization-community-1)에서 본인 계정으로 접근 조건에 동의하고 읽기 권한이 있는 Hugging Face 토큰을 만드세요.

Docker:

```sh
docker compose exec meetingbot /app/backend/.venv/bin/python /app/scripts/prepare_models.py --diarization-only --prompt-token
docker compose restart
```

네이티브 macOS/Linux:

```sh
backend/.venv/bin/python scripts/prepare_models.py --diarization-only --prompt-token
```

네이티브 Windows:

```powershell
backend\.venv\Scripts\python.exe scripts\prepare_models.py --diarization-only --prompt-token
```

프롬프트에 입력한 토큰은 화면에 표시되거나 설정 파일에 저장되지 않습니다. 자동화에서는 로컬 환경 변수 `HF_TOKEN`을 전달하고 `--prompt-token`을 생략할 수 있습니다. 다운로드된 모델은 STT 데이터 폴더의 `models/hub`에 보관되므로 Docker 볼륨이나 네이티브 데이터 백업에 함께 포함됩니다. 네이티브에서는 런처를 종료한 뒤 다시 열어 적용하세요.

## 환경 설정

기본 설치에는 `.env`나 `.env.rag` 복사가 필요 없습니다. 런처가 키·권한 저장소·허용 문서 폴더를 초기화합니다. 설치 후 필요한 값만 설정하세요.

- **네이티브:** `.env.example`을 참고해 `.env`에 STT 설정을 작성할 수 있습니다. RAG를 직접 구성하려면 `.env.rag.example`과 [RAG 설정 안내](rag/installation.md)를 참고하세요. 예제만 복사한 `.env.rag`는 초기 키·허용 폴더 설정이 없으므로 첫 설치 단계에서 그대로 사용하지 마세요.
- **Docker:** 호스트의 `.env` 파일은 컨테이너에 자동 전달되지 않습니다. 필요한 항목만 `compose.override.yaml`의 `environment`로 전달합니다. 컨테이너 데이터 경로는 `/data/stt`, `/data/rag`를 유지하세요.

예를 들어 방문자 접속을 끄고 키로만 접속하려면:

```yaml
# compose.override.yaml (개인 설정: 커밋하지 마세요)
services:
  meetingbot:
    environment:
      STT_KEYLESS_LOGIN: "false"
      RAG_KEYLESS_LOGIN: "false"
```

`docker compose up -d`로 반영합니다. 접속 키·토큰·실제 문서는 Git에 넣지 마세요. 원격 접속은 [Tailscale/HTTPS 안내](tailnet-access.md)를 참고하세요. Docker에서 AI 서버 주소 `127.0.0.1`은 컨테이너 자체를 뜻하므로, 연결할 AI 서버가 컨테이너에서 접근 가능한 주소를 사용해야 합니다.

## 백업과 업데이트

**백업:** 전사·색인 작업을 마친 뒤 서비스를 중지하세요. 네이티브는 `.runtime/`, `.rag-data/`, 직접 만든 `.env`·`.env.rag`·소스 폴더 설정과 외부 문서 원본을 함께 백업합니다. `.runtime`이 심볼릭 링크라면 실제 대상 디렉터리를 백업해야 합니다. Docker는 [볼륨 백업·복구 절차](https://docs.docker.com/engine/storage/volumes/#back-up-restore-or-migrate-data-volumes)로 `meetingbot-data` 볼륨 전체를 백업합니다. 백업에는 접속 키와 회의 자료도 포함됩니다.

**업데이트:** 아직 서명된 설치 프로그램·안정 릴리스 채널·자동 마이그레이션/롤백을 제공하지 않습니다. 변경 내용을 확인하고 데이터 백업을 만든 다음 적용하세요.

```sh
# Docker: 프로젝트 폴더에서
docker compose stop
git pull --ff-only
docker compose up --build -d
```

네이티브는 런처를 종료하고 `git pull --ff-only` 후 `python3 scripts/install.py`를 다시 실행합니다(Windows는 `py -3.12 scripts/install.py`). 잠금 파일에 맞는 의존성과 웹 화면이 다시 준비되며 기존 데이터는 유지됩니다. 데이터 스키마를 바꾸는 업데이트는 해당 변경의 별도 복구 안내를 우선 따르세요.

## 문제 해결과 검증 범위

| 증상 | 확인할 사항 |
|---|---|
| 시작 페이지가 열리지 않음 | `docker compose ps`/로그, 네이티브 실행 창, 포트 8765/8766 사용 여부 |
| `npm` / `ffmpeg` / `ffprobe`를 찾지 못함 | 도구 설치 후 PATH를 적용하고 새 터미널에서 설치 재시도 |
| 실제 전사가 준비되지 않음 | 음성 모델 설치 완료와 **사용하기** 적용 여부 |
| 모델 다운로드 실패 | 네트워크·남은 디스크·Community-1 접근 동의와 토큰 확인 |
| 실행 중 메모리 부족 | Small로 시작하고 다른 앱 종료, Docker 메모리 할당 확인 |
| RAG 관리자 키가 없다는 오류 | 수동 `.env.rag` 설정 여부와 RAG 초기화 절차 확인 |
| 다른 설치가 포트를 점유했다는 오류 | 기존 런처/서비스를 확인하고 의도한 설치 하나만 실행 |

macOS 개발 환경에서 설치/런처·모델 준비와 Windows 호환성 회귀 테스트를 수행했습니다. [Windows CI](../.github/workflows/windows.yml)는 한글·공백 경로에서 네이티브 설치·웹 빌드와 Windows 전용 파일/프로세스 테스트를 실행하도록 구성했습니다. Windows CI의 성공 결과와 실제 Windows PC의 음성·마이크 검증은 아직 확인하지 않았습니다. 실제 대용량 모델 다운로드, Linux 새 설치, Docker 이미지 전체 빌드 및 장시간 전사는 이번 검증에 포함하지 않았습니다.
