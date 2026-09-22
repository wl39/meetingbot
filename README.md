# Meetingbot · 회의봇

내 컴퓨터나 서버에 설치해서 사용하는 MIT 라이선스의 오픈소스 회의 전사·문서 검색 도구입니다. React + FastAPI 기반으로 음성을 로컬에서 처리하고, 대본과 문서를 설치한 장치에 보관합니다.

- **음성 전사:** 파일 업로드와 실시간 마이크 자막, Whisper Small / Large v3 Turbo 선택
- **대본 편집:** 화자 구분·이름 변경, 오디오와 대본 위치 연결, TXT/SRT/JSON 내보내기
- **자료 검색:** MD/TXT/CSV/TSV/XLSX 문서 검색과 근거 확인, 워크스페이스별 자료 관리
- **회의 도우미:** 연결한 AI와 자료를 이용해 발화에 관련된 근거·안내 제공
- **웹 관리:** 음성 엔진·모델 설치, 자료 청킹, AI 연결, 접속 권한 설정

기본 전사·문서 검색에는 유료 AI API가 필요하지 않습니다. AI 답변과 회의 도우미는 별도의 OpenAI 호환 AI 서버 연결이 필요하며, 외부 LLM 전송은 기본적으로 꺼져 있습니다. 화자 분석 모델은 별도 다운로드와 Hugging Face 접근 동의가 필요합니다.

## 필요한 사양

아래는 **사용자 1명·동시 전사 1개**를 위한 설치 계획 기준입니다. RAM은 장치 전체 메모리, 디스크는 설치 전 확보할 여유 공간이며, 성능을 보장하는 실측 최소 사양은 아닙니다.

| 항목 | 시작 기준 | 권장 |
|---|---|---|
| CPU | 64비트, 4코어 | 8코어 또는 Apple Silicon |
| RAM | 8 GB: Small 모델·짧은 파일 위주 | 16 GB 이상; Turbo·화자 분석·긴 회의는 32 GB 권장 |
| 디스크 · macOS/Windows 네이티브 | 15 GB 여유 | 25 GB 이상 + 보관할 자료 용량 |
| 디스크 · Linux 네이티브 / Docker | 40 GB 여유 | 60 GB 이상 + 보관할 자료 용량 |
| GPU | 필수 아님 | Apple Silicon 네이티브 설치 시 MLX 가속 |
| 네트워크 | 최초 패키지·모델 다운로드에 필요 | 외부 AI 사용 시 해당 서버 접속 필요 |

모델은 앱 설치 후 필요한 것만 받습니다. Small은 약 **0.5 GB**, Turbo는 약 **1.6–1.7 GB**, 문서 검색용 E5는 약 **0.5 GB**, 화자 분석 모델은 약 **34 MB**를 추가로 사용합니다. 엔진 패키지·다운로드 캐시·색인·업로드 자료는 별도입니다. 300분 오디오는 변환된 임시 PCM만 약 **1.15 GB**이며, 원본 최대 4 GiB를 포함해 **작업당 6 GiB 이상의 임시 여유 공간**도 확보하세요.

Docker Desktop에는 RAM을 최소 8 GB, 가능하면 12–16 GB 할당하세요. 호스트 운영체제가 쓸 메모리도 남겨야 합니다. 현재 Linux 의존성에는 CUDA 라이브러리가 포함돼 GPU를 사용하지 않아도 설치 공간이 큽니다. 기본 Docker 구성은 GPU를 연결하지 않으며, Faster Whisper 음성 인식은 CPU를 사용합니다.

지원 대상으로 구성한 환경은 **Windows 10/11 x64**, **macOS 14+ Apple Silicon**, **Linux x86_64/ARM64(glibc 2.28+)**입니다. Intel Mac은 Docker를 사용하세요. Windows ARM과 32비트 Windows 네이티브 설치는 지원하지 않습니다. Windows/Linux 실기기와 Docker 전체 빌드 검증은 아직 남아 있습니다. 용량 산정 근거는 [상세 사양](docs/hardware-requirements.md)을 참고하세요.

## Windows에서 바로 설치

Docker 없이 설치할 수 있습니다. Windows 10/11 **64비트 Intel/AMD PC**에서:

1. 저장소를 내려받아 압축을 풉니다. 가능하면 `C:\meetingbot`처럼 짧은 로컬 경로를 사용하세요.
2. **[Install-Windows.cmd](Install-Windows.cmd)**를 더블클릭합니다. 필요한 Python 3.12, Node.js, FFmpeg를 확인하고 누락된 도구는 WinGet으로 설치합니다. 설치 과정에서 Windows 권한 확인이 나타날 수 있습니다.
3. 설치 후 열린 화면에서 **설정 및 관리 → 음성 인식 → Faster Whisper CPU → Small → 설치 → 사용하기**를 선택합니다.
4. 다음부터는 생성된 **`Meetingbot.cmd`**를 더블클릭합니다. 정상 종료는 실행 창에서 **Ctrl+C**를 누릅니다.

Git이 설치되어 있다면 PowerShell에서 아래 세 줄로 시작할 수 있습니다.

```powershell
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
.\Install-Windows.cmd
```

WinGet이 없거나 회사 PC에서 설치가 제한되면 [Windows 상세 안내](docs/windows.md)의 수동 설치를 사용하세요. 기본 전사는 CPU를 사용하며 NVIDIA GPU는 필수가 아닙니다. RAM **16 GB**, SSD **25 GB 이상**을 권장합니다.

## 빠른 설치 · Docker

[Git](https://git-scm.com/downloads)과 [Docker Desktop](https://www.docker.com/products/docker-desktop/) 또는 Linux의 Docker Engine + Compose를 설치한 뒤 실행합니다.

```sh
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
docker compose up --build -d
```

브라우저에서 **[http://127.0.0.1:8765](http://127.0.0.1:8765)**를 엽니다. 첫 빌드는 패키지 다운로드로 시간이 걸립니다. `docker compose ps`로 실행 상태를 확인할 수 있습니다.

관리 기능을 사용하려면 아래 명령으로 확인한 키를 화면의 **관리자 로그인**에 입력합니다. 이 키는 다른 사람과 공유하지 마세요.

```sh
docker compose exec meetingbot cat /data/stt/local-token
```

첫 실행 후:

1. **설정 및 관리 → 음성 인식**에서 지원 엔진과 **Small** 모델을 **설치**합니다.
2. 설치가 끝나면 **사용하기**를 눌러 적용하고, 짧은 음성 파일로 전사를 확인합니다.
3. 자료 검색을 쓰려면 설정에서 임베딩 모델을 설치하고 워크스페이스에 문서를 올립니다.
4. AI 답변·회의 도우미를 쓰려면 **AI 연결**을 설정하고 사용할 워크스페이스의 외부 전송을 허용합니다.

모델을 받기 전에는 웹 화면만 사용할 수 있고 실제 전사는 준비되지 않습니다. 화자 분석은 [별도 준비 절차](docs/installation.md#화자-분석-모델-선택)를 따르세요.

```sh
docker compose stop          # 중지: 데이터 유지
docker compose start         # 다시 실행
docker compose logs --tail=100 meetingbot  # 시작 문제 확인
```

대본·설정·모델·문서는 Docker의 `meetingbot-data` 볼륨에 보관됩니다. **`docker compose down -v`는 이 데이터를 삭제합니다.** 기본 접속은 설치한 컴퓨터에서만 가능하며, 원격 사용은 [HTTPS 접속 안내](docs/tailnet-access.md)를 참고하세요.

## 직접 설치 · Apple Silicon 가속 / 개발 환경

Git, **Python 3.11 또는 3.12**, **Node.js 22 LTS**, **FFmpeg(ffprobe 포함)**를 준비합니다. Apple Silicon Mac에서 Homebrew를 사용한다면 `brew install python@3.12 node@22 ffmpeg`로 설치할 수 있습니다. `node`, `npm`, `ffmpeg`, `ffprobe`가 PATH에서 실행되어야 합니다.

```sh
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
python3 scripts/install.py
```

Windows에서는 마지막 줄 대신 `py -3.12 scripts/install.py`를 실행합니다. 설치 스크립트는 uv와 Python 3.12 실행 환경, STT/RAG 의존성, 웹 화면을 준비하고 브라우저를 엽니다. 이후에는 생성된 실행 파일을 열면 됩니다.

| 운영체제 | 실행 파일 |
|---|---|
| macOS | `Meetingbot.command` |
| Windows | `Meetingbot.cmd` |
| Linux | `./Meetingbot.sh` |

실행 창을 유지해야 서비스가 동작하며 Ctrl+C로 종료합니다. 모델 설치 순서는 Docker와 같습니다. 기본 데이터 위치는 `.runtime/`(전사·권한·음성 모델)과 `.rag-data/`(문서·색인·임베딩)입니다. 첫 설치에는 `.env`를 만들 필요가 없습니다. 설정 변경, 백업, 업데이트와 문제 해결은 [상세 설치 안내](docs/installation.md)를 참고하세요.

## 사용 범위

- 파일 한도는 **300분·4 GiB**, 실시간 마이크 입력은 **5분**입니다. 한 번에 하나의 전사 작업을 처리합니다.
- 긴 파일은 나눠 전사합니다. 실제 300분 회의의 처리 속도와 다인 화자 정확도는 아직 검증되지 않았습니다.
- 일반 접속은 방문자로 연결됩니다. 전사 기록은 사용자별로 구분되고, 공용 자료 검색은 방문자에게도 열립니다. 키 전용 접속으로 바꾸는 방법은 [보안 안내](SECURITY.md)를 참고하세요.
- 모델 다운로드 후 전사와 문서 검색은 로컬에서 처리합니다. 외부 AI를 켜면 선택한 발화·질문·검색 근거가 연결된 서버로 전송됩니다.
- 현재는 소스 설치 방식이며, 서명된 OS별 설치 프로그램과 웹 자동 업데이트는 제공하지 않습니다.

## 개발과 기여

```sh
uv sync --project backend --python 3.12 --locked
uv sync --project rag --python 3.12 --locked
uv run --project backend pytest backend/tests -q
uv run --project rag pytest rag/tests -q
uv run --project backend pytest scripts/tests -q
npm --prefix frontend ci
npm --prefix frontend test
npm --prefix frontend run build
```

[기여 안내](CONTRIBUTING.md) · [소스 구조](docs/code-structure.md) · [전사 API](docs/stt-api.md) · [RAG API](docs/rag/api.md) · [회의 도우미](docs/meeting-assistant.md) · [공개 데모](docs/public-demo.md)

## 라이선스

프로젝트 코드는 [MIT License](LICENSE)로 공개합니다. 모델·외부 패키지는 각자의 라이선스와 접근 조건을 따르며 저장소에 모델 가중치를 포함하지 않습니다. [음성 의존성 고지](docs/licenses.md) · [RAG 의존성 고지](docs/rag/licenses.md)
