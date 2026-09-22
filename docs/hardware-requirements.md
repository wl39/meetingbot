# 실행 환경과 저장 공간

아래 수치는 **한 사람이 한 번에 한 건을 처리할 때의 설치·운영 계획용 권장치**입니다. 앱 전체의 최대 메모리를 플랫폼별로 실측한 최소 사양은 아닙니다. 음성 길이, 함께 설치한 모델, 화자 분석, 문서 수와 다른 프로그램의 사용량에 따라 더 많은 자원이 필요합니다.

## 권장 사양

| 항목 | 가벼운 시작 | 일반 사용 권장 |
| --- | --- | --- |
| CPU | 64비트 4코어 | 8코어 이상 또는 Apple Silicon |
| 시스템 메모리 | 8 GB: Small 모델과 짧은 파일부터 시작 | 16 GB 이상; Turbo·화자 분석·많은 문서·장시간 회의는 32 GB 권장 |
| 네이티브 macOS / Windows 설치 전 SSD 여유 공간 | 15 GB | 25 GB 이상 |
| 네이티브 Linux / Docker 설치 전 SSD 여유 공간 | 40 GB | 60 GB 이상 |
| GPU | 필수 아님 | Apple Silicon 네이티브 설치는 MLX 가속 사용 |
| 네트워크 | 최초 패키지·모델 다운로드에 필요 | 다운로드 후 로컬 전사·임베딩은 로컬 모델 사용 |

SSD 여유 공간은 설치 파일 크기와 다릅니다. 패키지 압축 해제, 두 Python 환경, 모델, 다운로드/빌드 캐시를 고려한 예산이며 자료·녹음·백업 보관 공간은 별도로 잡으세요. Docker Desktop에서는 VM에 메모리 8 GB 이상, 가능하면 16 GB를 할당하고 호스트 운영체제에도 여유 메모리를 남기세요. CPU 환경에서 실시간 전사 속도는 보장하지 않습니다.

AI 답변을 생성하는 LLM은 별도로 연결합니다. 위 사양에는 사용자가 별도 설치한 로컬 LLM 서버의 메모리·GPU·모델 공간이 포함되지 않습니다.

## 플랫폼별 실행 방식

| 환경 | 음성 인식 방식 | 설치 조건과 확인 범위 |
| --- | --- | --- |
| Apple Silicon Mac 네이티브 | MLX Whisper | macOS 14 이상. 현재 잠금 파일의 MLX·PyTorch 휠 기준. 기존 개발 환경에서 실행 검증 |
| Windows 10/11 x64 네이티브 | Faster Whisper CPU / int8 | `Install-Windows.cmd`가 Python 3.12·Node.js 22·FFmpeg를 준비. Windows CI 구성 포함, 실기기 전체 설치 검증은 별도 필요. [Windows 안내](windows.md) |
| Linux x86_64 / arm64 네이티브 | Faster Whisper CPU / int8 | 현재 PyTorch 휠은 glibc 2.28 이상 대상. Node.js 22, FFmpeg 필요. 배포판별 전체 설치 검증은 별도 필요 |
| Docker: Windows / macOS / Linux | Linux 컨테이너의 Faster Whisper CPU / int8 | Docker와 Compose 필요. Mac에서도 MLX 가속을 사용할 수 없음 |
| Intel Mac | Docker의 CPU 경로 사용 | 현재 잠금 파일에 Intel macOS용 PyTorch 휠이 없어 전체 앱 네이티브 설치 대상에서 제외 |
| Windows ARM | 지원 대상 아님 | 현재 음성 엔진 카탈로그와 PyTorch 잠금 파일에 네이티브 지원 없음 |

설치 스크립트는 Python 3.12를 준비하며 프로젝트 선언 범위는 Python 3.11–3.12입니다. Docker에는 Node.js 빌드 단계, Python, FFmpeg가 포함됩니다.

현재 Faster Whisper 구현은 CPU로 고정되어 있고 기본 Compose에는 NVIDIA GPU 전달 설정이 없습니다. 별도 CUDA 전사 설치를 제공하는 것으로 해석하면 안 됩니다. 화자 분석 코드는 사용 가능한 CUDA/MPS/CPU를 선택할 수 있지만, 기본 배포에서 NVIDIA 가속 구성을 검증한 것은 아닙니다.

## 모델 다운로드 용량

2026-09-21에 모델 제공자의 파일 목록을 확인한 대략적인 **10진수** 용량입니다. 모델을 여러 개 설치하면 합산되며 실행 중 RAM 사용량과는 다릅니다. 모델 버전이나 캐시 보관 방식에 따라 실제 점유량이 달라질 수 있습니다.

| 모델 | 다운로드 공간 | 근거 |
| --- | --- | --- |
| Whisper Small | 약 0.5 GB | [MLX: 481 MB](https://huggingface.co/mlx-community/whisper-small-mlx/tree/main), [Faster Whisper: 486 MB](https://huggingface.co/Systran/faster-whisper-small/tree/main) |
| Whisper Large v3 Turbo | 약 1.7 GB | [MLX: 1.61 GB](https://huggingface.co/mlx-community/whisper-large-v3-turbo/tree/main), [Faster Whisper: 1.62 GB](https://huggingface.co/dropbox-dash/faster-whisper-large-v3-turbo/tree/main) |
| Multilingual E5 Small: 자료 검색 | 필요한 PyTorch 가중치·토크나이저 약 0.5 GB | [가중치 471 MB와 토크나이저 파일 목록](https://huggingface.co/intfloat/multilingual-e5-small/tree/main). ONNX·OpenVINO·중복 가중치까지 전체 저장소를 받으면 약 2.3 GB |
| Community-1: 선택 화자 분석 | 약 34 MB | [공개 파일 메타데이터](https://huggingface.co/api/models/pyannote/speaker-diarization-community-1/tree/main?recursive=true). 패키지 공간은 별도이며 모델 접근 조건 동의와 Hugging Face 토큰 필요 |

모델 다운로드는 웹 설정의 명시적 설치 동작에서 진행합니다. Community-1은 별도 준비가 필요합니다. Small과 Turbo가 모두 설치되면 워커가 두 모델을 준비하므로 RAM 사용량도 늘어날 수 있습니다. 처음에는 Small 한 개로 시작하세요.

## 긴 녹음의 임시 공간

앱은 녹음을 16 kHz, 모노, float32 PCM으로 변환합니다. PCM만 계산하면 `16,000 × 4 × 3,600` 바이트, 즉 **시간당 약 230 MB**입니다. 최대 300분 입력은 약 1.15 GB의 PCM과 최대 4 GiB의 업로드 원본 공간을 함께 사용하므로, 위 설치 예산 외에 **작업당 6 GiB 이상의 임시 여유 공간**을 두세요. 원음 보관을 켜거나 여러 결과를 계속 보관하면 추가 저장 공간이 필요합니다.

화자 분석은 전체 녹음을 대상으로 합니다. 전사를 구간별로 처리해도 전체 작업 메모리가 항상 일정하다는 뜻은 아닙니다. 최대 300분·4 GiB는 입력 제한이며 해당 길이의 실제 회의 처리 속도와 정확도 보장은 아닙니다.

## 수치의 근거와 한계

- 현재 Apple Silicon 개발 환경의 디렉터리 크기만 측정했을 때 STT 가상 환경은 약 1.5 GiB, RAG 가상 환경은 약 1.0 GiB, 프론트엔드 개발 의존성은 약 164 MiB였습니다. 캐시·모델·녹음은 제외했으며 새 설치 파일이나 Docker 이미지의 실측 크기가 아닙니다.
- 현재 Linux x86_64 잠금 파일에서 PyTorch·NVIDIA 라이브러리·Triton 휠의 압축 다운로드 크기 합은 약 2.99 GB입니다. GPU를 쓰지 않아도 이 의존성이 포함되며 설치 후에는 압축이 풀립니다. STT와 RAG는 별도 환경을 만들기 때문에 Linux/Docker의 저장 공간을 더 넉넉하게 안내합니다. 실제 빌드 캐시 크기는 Docker 설정에 따라 달라집니다.
- [Faster Whisper 공식 벤치마크](https://github.com/SYSTRAN/faster-whisper#small-model-on-cpu)는 Small CPU int8 단독 처리에 약 1,477 MB RAM을 보고합니다. 이는 회의봇의 웹 서버·자료 검색·화자 분석을 합친 측정값이 아니므로 앱 전체 최소 RAM으로 사용할 수 없습니다.
- 코드 기준: [음성 엔진·모델 카탈로그](../backend/app/modules/system/catalog.py), [CPU 음성 인식](../backend/app/modules/stt/engines/faster_whisper_engine.py), [워커의 모델 준비](../backend/app/modules/stt/workers.py), [PCM 변환](../backend/app/modules/stt/audio.py), [STT 잠금 파일](../backend/uv.lock), [RAG 잠금 파일](../rag/uv.lock).

플랫폼별 깨끗한 설치, 실제 긴 회의의 메모리 최고치와 처리 속도는 추가 검증이 필요합니다. 이 문서의 RAM·SSD 권장치는 그 검증을 대신하지 않습니다.
