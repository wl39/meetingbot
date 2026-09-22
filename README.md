# Meetingbot · 회의봇

내 컴퓨터나 서버에 설치해서 사용하는 **오픈소스 회의 전사·문서 검색 도구**입니다. 음성 인식과 문서 검색을 로컬에서 처리하고, 대본과 자료를 설치한 장치에 보관합니다.

- 음성 파일 전사·실시간 자막, 화자 구분, 대본 편집 및 TXT/SRT/JSON 내보내기
- MD/TXT/CSV/TSV/XLSX 문서 검색과 근거 확인
- 별도로 연결한 AI를 이용한 문서 질문과 회의 도우미

**사용할 운영체제의 사양을 확인한 뒤, 같은 항목의 설치 명령을 실행하세요.**

[Windows](#windows) · [Linux](#linux) · [macOS](#macos) · [Docker](#docker) · [설치 후 설정](#설치-후-설정) · [데이터와 업데이트](#데이터와-업데이트)

> 아래 사양은 **사용자 1명·동시 전사 1개**의 설치 계획 기준입니다. RAM 8 GB는 Small 모델로 짧은 파일을 시험하는 수준이며, 일반 사용은 16 GB, 긴 회의·Turbo·화자 분석을 함께 사용하면 32 GB를 권장합니다. 디스크 수치는 설치 전 확보할 **여유 공간**이며, 운영체제별 실측 최소 사양이나 처리 속도를 보장하는 값은 아닙니다.

## Windows

### 필요한 사양

| 항목 | 시작 기준 | 권장 |
|---|---|---|
| 운영체제 | Windows 10/11, Intel·AMD **x64** | 동일 |
| CPU | 64비트 4코어 | 8코어 이상 |
| RAM | 8 GB | 16 GB 이상, 긴 회의·화자 분석은 32 GB |
| 디스크 여유 공간 | 15 GB | SSD 25 GB 이상 + 자료 보관 공간 |
| GPU | 필수 아님 | 기본 전사는 CPU 사용 |
| 음성 엔진 | Faster Whisper CPU / int8 | Small로 시작, 필요하면 Turbo 추가 |

Windows ARM과 32비트 Windows는 현재 네이티브 설치 대상이 아닙니다.

### 설치

**준비:** [Git](https://git-scm.com/downloads/win)과 [WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/). 설치 도우미가 Python 3.12 x64, Node.js 22, FFmpeg/ffprobe를 확인하고 없는 도구를 설치합니다.

PowerShell에서 실행합니다.

```powershell
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
.\Install-Windows.cmd
```

Git 대신 저장소의 **Code → Download ZIP**으로 받은 경우에는 압축을 완전히 풀고 `Install-Windows.cmd`를 더블클릭하면 됩니다. 가능하면 `C:\meetingbot`처럼 짧은 로컬 경로를 사용하세요.

**다음 실행:** 생성된 `Meetingbot.cmd` 더블클릭. **종료:** 실행 창에서 `Ctrl+C`.

설치가 끝나면 아래 [설치 후 설정](#설치-후-설정)을 진행하세요. WinGet 없이 설치하는 방법과 오류 해결은 [Windows 상세 안내](docs/windows.md)에 있습니다.

## Linux

### 필요한 사양

| 항목 | 시작 기준 | 권장 |
|---|---|---|
| 운영체제 | **x86_64 또는 ARM64**, glibc 2.28 이상 | 아래 명령은 Ubuntu 24.04 LTS 기준 |
| CPU | 64비트 4코어 | 8코어 이상 |
| RAM | 8 GB | 16 GB 이상, 긴 회의·화자 분석은 32 GB |
| 디스크 여유 공간 | 40 GB | SSD 60 GB 이상 + 자료 보관 공간 |
| GPU | 필수 아님 | 기본 전사는 CPU 사용 |
| 음성 엔진 | Faster Whisper CPU / int8 | Small로 시작, 필요하면 Turbo 추가 |

현재 Linux 의존성에는 CUDA 라이브러리가 포함되어 **GPU를 사용하지 않아도 설치 공간이 큽니다**. 기본 음성 인식에는 NVIDIA GPU 가속이 연결되어 있지 않습니다.

### 설치

**준비:** Git, Python 3.11 또는 3.12와 `venv`, **[Node.js 22](https://nodejs.org/en/download)**와 npm, FFmpeg/ffprobe, OpenMP 런타임(`libgomp1`). Node.js는 별도로 준비하세요. 아래 Ubuntu 패키지 명령에는 포함하지 않았습니다.

Ubuntu 24.04 LTS에서:

```sh
sudo apt update
sudo apt install -y git python3 python3-venv ffmpeg libgomp1

# Node.js 22와 npm 설치 여부 확인
node --version
npm --version

git clone https://github.com/wl39/meetingbot.git
cd meetingbot
python3 scripts/install.py
```

다른 배포판에서는 같은 도구를 해당 배포판의 패키지 관리자로 준비한 뒤 설치 스크립트를 실행하세요. 설치 스크립트가 앱용 Python 3.12 환경과 웹 화면을 준비합니다.

**다음 실행:** 프로젝트 폴더에서 `./Meetingbot.sh`. **종료:** 실행 터미널에서 `Ctrl+C`.

GUI가 없는 서버에서는 아래 명령으로 실행할 수 있습니다. 기본 접속 주소는 서버 자신의 `127.0.0.1:8765`이며, 다른 컴퓨터에서 접속하려면 [원격 접속](docs/tailnet-access.md)을 별도로 설정해야 합니다.

```sh
backend/.venv/bin/python scripts/launch.py --no-browser
```

설치가 끝나면 아래 [설치 후 설정](#설치-후-설정)을 진행하세요.

## macOS

### 필요한 사양

| 항목 | 시작 기준 | 권장 |
|---|---|---|
| 운영체제 | **macOS 14 이상, Apple Silicon** | 동일 |
| CPU | Apple M 시리즈 | 8코어 이상 |
| RAM | 통합 메모리 8 GB | 16 GB 이상, 긴 회의·화자 분석은 32 GB |
| 디스크 여유 공간 | 15 GB | SSD 25 GB 이상 + 자료 보관 공간 |
| GPU | Apple Silicon 내장 GPU 사용 | 별도 GPU 불필요 |
| 음성 엔진 | MLX Whisper | Small로 시작, 필요하면 Turbo 추가 |

Intel Mac은 현재 네이티브 설치 대상이 아닙니다. 아래 [Docker 설치](#docker)를 사용하세요.

### 설치

**준비:** [Homebrew](https://brew.sh/). 터미널에서 필수 도구와 앱을 설치합니다.

```sh
brew install git python@3.12 node@22 ffmpeg
export PATH="$(brew --prefix node@22)/bin:$PATH"

git clone https://github.com/wl39/meetingbot.git
cd meetingbot
python3.12 scripts/install.py
```

**다음 실행:** 생성된 `Meetingbot.command` 더블클릭. **종료:** 실행 창에서 `Ctrl+C`.

설치가 끝나면 아래 [설치 후 설정](#설치-후-설정)을 진행하세요.

## Docker

Windows·Linux·macOS에서 사용할 수 있는 **대체 설치 방법**입니다. 앱용 Python·Node.js·FFmpeg를 호스트에 따로 설치할 필요가 없습니다.

| 항목 | Docker 설치 기준 |
|---|---|
| 필수 도구 | Git + Docker Desktop, 또는 Linux Docker Engine + Compose |
| CPU | 64비트 4코어 이상, 8코어 권장 |
| RAM | 앱에 8 GB 이상, 가능하면 16 GB 할당. 호스트 운영체제용 메모리는 별도 확보 |
| 디스크 여유 공간 | 40 GB 이상, SSD 60 GB 이상 권장 + 자료 보관 공간 |
| 음성 엔진 | 모든 호스트에서 Faster Whisper CPU / int8 |
| GPU | 기본 구성은 GPU를 연결하지 않음. Mac에서도 MLX 가속 사용 불가 |

[Docker Desktop](https://www.docker.com/products/docker-desktop/) 또는 Linux용 Docker Engine과 Compose를 준비한 뒤 실행합니다.

```sh
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
docker compose up --build -d
docker compose ps
```

**접속:** [http://127.0.0.1:8765](http://127.0.0.1:8765). 관리자 설정을 열려면 다음 명령으로 확인한 키를 화면의 **관리자 로그인**에 입력합니다.

```sh
docker compose exec meetingbot cat /data/stt/local-token
```

**다음 실행:** `docker compose start`. **종료:** `docker compose stop`.

설치가 끝나면 아래 공통 설정을 진행하세요.

## 설치 후 설정

설치가 끝나면 웹 화면은 열리지만 **음성 모델을 설치하기 전에는 실제 전사를 사용할 수 없습니다**. 네이티브 설치는 브라우저를 자동으로 열며, 직접 접속할 때는 [http://127.0.0.1:8765](http://127.0.0.1:8765)를 사용합니다.

런처가 연 브라우저는 관리자 세션으로 연결됩니다. 주소를 직접 열었다면 프로젝트의 `.runtime/local-token` 파일에 있는 키를 **관리자 로그인**에 입력하세요. Docker는 위의 키 확인 명령을 사용합니다.

1. **설정 및 관리 → 음성 인식**에서 지원 엔진의 **Small → 설치 → 사용하기**를 선택합니다.
2. 짧은 음성 파일을 올려 전사를 확인합니다.
3. 문서 검색도 사용하려면 **자료 검색** 설정에서 임베딩 모델을 설치하고 워크스페이스에 문서를 올립니다.
4. AI 답변·회의 도우미를 사용하려면 **AI 연결**에서 OpenAI 호환 서버를 연결하고 해당 워크스페이스의 외부 전송을 허용합니다.

### 모델 용량과 작업 공간

| 사용할 기능 | 필요한 모델 | 다운로드 용량 |
|---|---|---|
| 기본 음성 전사 | Whisper Small | 약 0.5 GB |
| 더 큰 음성 모델 선택 | Whisper Large v3 Turbo | 약 1.7 GB |
| 문서 검색 | Multilingual E5 Small | 약 0.5 GB |
| 화자 분석 — 선택 | Community-1 | 약 34 MB, Hugging Face 접근 동의·토큰 필요 |

화자 분석은 [별도 모델 준비 절차](docs/installation.md#화자-분석-모델-선택)를 따릅니다. 위 운영체제별 디스크 기준은 패키지·모델·캐시를 고려한 예산이며, 이 표는 개별 모델의 다운로드 크기입니다. 실행 중 RAM 사용량과는 다릅니다. 보관할 녹음·문서·색인·백업 공간은 별도로 잡고, 최대 300분 파일을 처리할 때는 **작업당 6 GiB 이상의 임시 여유 공간**도 확보하세요. 자세한 산정 근거는 [사양과 용량](docs/hardware-requirements.md)에 있습니다.

기본 전사·문서 검색에는 유료 AI API가 필요하지 않습니다. 최초 패키지·모델 다운로드에는 인터넷이 필요하고, 준비된 모델은 로컬에서 사용합니다. 외부 AI는 기본적으로 꺼져 있으며, 활성화하면 질문·선택된 발화·검색 근거가 연결한 서버에 전달됩니다. 별도로 설치하는 로컬 LLM 서버의 자원은 위 사양에 포함하지 않았습니다.

## 데이터와 업데이트

| 항목 | 네이티브 설치 | Docker 설치 |
|---|---|---|
| 전사·권한·음성 모델 | 프로젝트의 `.runtime/` | `meetingbot-data` 볼륨의 `/data/stt` |
| 문서·색인·임베딩 | 프로젝트의 `.rag-data/` | 같은 볼륨의 `/data/rag` |
| 실행 로그 | `.runtime/logs/` | `/data/stt/logs/` |
| 업데이트 | 종료 → 백업 → `git pull --ff-only` → 설치 스크립트 재실행 | 종료 → 볼륨 백업 → `git pull --ff-only` → `docker compose up --build -d` |

첫 설치에는 `.env`를 만들 필요가 없습니다. 네이티브 실행 창을 유지해야 서비스가 동작합니다. Docker의 **`docker compose down -v`는 저장된 데이터를 삭제합니다**. 설정 변경·백업·복구·문제 해결은 [운영 안내](docs/installation.md)를 참고하세요.

## 현재 지원 범위

- 파일 입력은 **최대 300분·4 GiB**, 실시간 마이크는 **최대 5분**, 동시 전사는 **1개**입니다.
- 일반 접속은 방문자로 연결됩니다. 개인 전사 기록은 사용자별로 구분되지만 공용 자료 검색은 방문자에게도 열립니다. 접근 설정은 [보안 안내](SECURITY.md)를 참고하세요.
- Windows용 설치 도우미와 [자동 테스트](https://github.com/wl39/meetingbot/actions/workflows/windows.yml)를 제공합니다. Windows/Linux 실기기·Docker 전체 설치와 실제 긴 회의의 성능은 추가 검증이 필요합니다.
- 현재 배포 방식은 소스 설치입니다. 서명된 OS별 설치 프로그램과 웹 자동 업데이트는 아직 제공하지 않습니다.

## 개발과 라이선스

[기여·테스트 안내](CONTRIBUTING.md) · [소스 구조](docs/code-structure.md) · [전사 API](docs/stt-api.md) · [RAG API](docs/rag/api.md)

프로젝트 코드는 [MIT License](LICENSE)를 따릅니다. 모델·외부 패키지에는 각자의 라이선스와 접근 조건이 적용되며, 저장소에는 모델 가중치를 포함하지 않습니다. [음성 의존성 고지](docs/licenses.md) · [RAG 의존성 고지](docs/rag/licenses.md)
