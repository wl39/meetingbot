# STT 검증 결과 — 2026-09-09 UTC

이 문서는 당시 개발 환경의 검증 기록이다. 테스트 개수·모델 준비 상태·성능 수치는 새 설치나 현재 버전의 측정값이 아니다. 개인 경로와 접속 주소는 `YOUR_*` 자리표시자로 바꾸었으며, 새 설치는 [설치 안내](installation.md)를 따른다.

## 대본 모드와 재생 싱크 — 2026-09-09 PDT

- 완료/부분 완료된 전사에서 사용자가 `대본 모드로 변환`을 눌러야 변환됩니다. 발화별 보기로 돌아가 원문과 화자 배정을 수정할 수 있습니다.
- 같은 화자의 발화는 사이 공백이 3초 이하이면 묶습니다. 같은 화자 사이의 2초 이하 미확정 구간도 포함하되, 겹친 발화와 사용자가 직접 미확정으로 지정한 구간은 추정하지 않습니다. 미확정 구간 포함 여부를 표시하며 원문·화자 배정·기존 내보내기 데이터는 변경하지 않습니다.
- 요청 예시의 네 발화가 `화자 A 02:00.1 ~ 02:26.0` 대본 하나로 변환됩니다. 대본을 클릭하면 시작 시점부터 재생하고 전체 대본 범위를 파형에 강조합니다. 이후 재생은 계속 이어집니다.
- 플레이어의 `대본 싱크` 라디오 버튼은 기본 끄기입니다. 켜면 현재 대본을 강조하고 대본 패널 안에서 자동 이동합니다. 발화별 보기, 일시 정지 중 탐색, 앞뒤 탐색에도 적용됩니다.
- 프론트엔드 35개, STT 86개, RAG 116개 테스트 통과. TypeScript/Vite 빌드 통과.
- `node scripts/stt_script_ui_smoke.mjs`: 합성 API/무음 WAV로 수동 변환, 미확정 구간 보존, 실제 HTML 오디오 클릭 재생, 선택 범위, 싱크 켜기/끄기, 재생 중 이동, 역방향 탐색, 발화별 싱크, 모바일 가로 넘침 검증 통과. 화면은 `.runtime/stt-script-qa`에 저장합니다. 실제 음성 인식 정확도는 이 테스트의 검증 대상이 아닙니다.

## 검증 상태

현재는 독립 모듈 구현, 모의 계약 검증, 실제 Whisper small/Silero/Community-1의 1인 합성 음성 스모크 검증까지 완료했습니다. **다인 실제 회의 정확도와 하드웨어 마이크 연속 녹음은 미검증**입니다. 아래 초기 결과의 Community-1 미준비 상태는 과거 기록이며, 마지막 「HF 준비 후 전체 파이프라인」 절이 최신 상태입니다.

환경: macOS 26.6.2, Apple M1, RAM 8GB, arm64, Python 3.12.14, Node 24.20.0, FFmpeg 9.0.1. 패키지는 `backend/uv.lock`, `frontend/package-lock.json`에 고정했습니다. Whisper small commit: `45f3915923c7a79a5a5b5a7d909d39aeb0e5630e`.

## 자동 테스트

- Python **33개 통과**: 실제 FFmpeg 파일 디코딩 + 모의 ASR/화자 엔진, 파일 단계 처리, 오디오 보관/재생/재처리, 수정 충돌, 이벤트 중복·revision 역전, 화자 ID 재매핑, 모호한 병합, 짧은 화자 근거, 발언 분할/retract, 수동 필드 보호, 단일 활성 작업, 삭제 후 결과 무효화, 재시작 복구, 파일 용량·길이, 무음, PCM 프레임·44.1kHz 리샘플링 시간축, 누락, 중지 sequence 확인, 마지막 짧은 프레임, 연결 중단 후 정리, Origin/인증/Host 제한.
- 프론트엔드 **3개 통과**: PCM 이진 계약/64비트 오프셋, 실제 AudioWorklet 소스의 mono 변환과 마지막 짧은 프레임 flush 순서, 늦은 snapshot 폐기.
- TypeScript 검사 + Vite 프로덕션 빌드 통과.
- Ruff 검사 통과. 프론트엔드는 Prettier로 정리했습니다.
- npm audit: production/development 의존성 모두 보고된 취약점 0개. 실행 시점 검사이며 향후 취약점 부재를 보장하지 않습니다.
- 테스트 의존성에서 Starlette/httpx 및 anyio의 deprecation warning 2건이 출력됩니다. 테스트 실패는 아닙니다.

재현: backend에서 `uv run pytest -q`, `uv run ruff check app`; frontend에서 `npm run build`, `npm test`.

## 실제 모델 — 파일 단독 스모크

macOS Yuna 합성 한국어 음성 5.82025초를 사용했습니다. 실제 사람이 말하는 회의 샘플이 아닙니다.

정답 문장: “오늘은 로그인 기능을 확인하겠습니다. 배포 일정은 금요일입니다. 네, 알겠습니다.”

| 구간 | 측정 |
|---|---:|
| 모델 로드 | 24.239초 |
| 첫 추론 | 4.157초, RTF 0.714 |
| 두 번째 추론 | 0.807초, RTF 0.139 |
| 단어 타임스탬프 | 9개, 범위·순서 검사 통과 |
| Silero ONNX | 음성 감지 확인, 별도 무음 입력에서는 감지 없음 |

인식 결과에서 **배포 → 개포** 오류가 있었습니다. CER/DER은 실험 코퍼스·정규화 규칙을 아직 정하지 않아 보고하지 않습니다.

`/usr/bin/sandbox-exec -p '(version 1) (allow default) (deny network*)' .../python scripts/smoke_real.py`로 OS 수준 네트워크 차단 상태에서 성공했습니다. 다운로드는 이전 단계에서 수행했습니다. 이 오프라인 검증 범위는 **Whisper·VAD**이며, Community-1까지 검증한 결과가 아닙니다.

원시 결과: [real-smoke.json](real-smoke.json). 재실행 시 준비된 합성 WAV와 모델 캐시가 필요합니다.

## 실제 모델 — 실시간 프로토콜 스모크

같은 합성 음성을 44.1kHz로 변환해 150ms PCM 프레임을 실제 시간 간격으로 전송했습니다. 서버에서 Silero VAD와 실제 MLX Whisper를 사용했으며 사용자 마이크는 열지 않았습니다.

- 첫 자막: 세션 시작 후 3.491초.
- partial 자막 및 stable 전환 관찰.
- 입력/처리 완료 위치: 모두 5,820ms. 종료 시 처리 지연 0ms.
- 전체 세션 처리: 6.843초.
- 마지막 ASR 추론: 0.667초.
- 5분 상한의 사전 할당 PCM 버퍼: 19,264,000바이트. 프로세스 전체 메모리가 아닙니다.
- 화자 엔진 미준비로 예상대로 PARTIAL + 미확정 화자, 텍스트 보존.

실시간 최종 인식에는 “기능을” 누락, “일정은 → 걱정은” 등의 오류가 있었습니다. 짧은 창 반복 인식·안정화 병합의 품질 개선이 필요합니다. 단일 짧은 시험으로 장시간 실시간 유지 능력을 판단하지 않습니다.

원시 결과: [real-stream-smoke.json](real-stream-smoke.json), 재현 스크립트: `scripts/smoke_stream.py`.

## 브라우저 검증

Codex 내장 브라우저에서 로컬 인증 → 파일 선택 → 실제 전사 시작 → PARTIAL 대본 표시 → “배포”로 수동 교정 → corrected 표시와 저장된 대본을 확인했습니다. 파일 화면과 실시간 화면의 레이아웃, 모델 준비 상태, 비활성 버튼을 확인했습니다. 실제 마이크 권한 획득·입력 장치·음질 검증은 수행하지 않았습니다.

## 미실행

Community-1 가중치 다운로드/CPU 추론/오프라인 실행, 2~3인 교대 발화 및 8인 음성, 겹친 실제 발화, 실제 화자 전환 정확도, 긴 무음 후 동일 인물 유지 정확도, 실제 마이크 5분 연속 녹음, large-v3-turbo 비교, 한국어 정답 코퍼스 CER, 화자 정답 구간 DER, 지연 분포·전체 프로세스 메모리 측정. 모의 테스트 통과를 이 항목들의 통과로 해석하지 않습니다.

## Tailscale 확장 검증 — 2026-09-09 UTC

사용자 요청으로 tailnet 원격 접속을 추가했습니다. Python 테스트는 **38개**, 프론트엔드 테스트는 **3개**가 통과했습니다. 추가 검증은 HTTPS Origin/CORS, 인증 유지, IP HTTP→HTTPS 이동, 원격 WebSocket handshake/stop, public_origin 설정 검증입니다. TypeScript/Vite 빌드와 Ruff도 통과했습니다.

실제 Tailscale Serve 경로로 확인한 결과:

- `http://YOUR_TAILSCALE_IP:8765/` → HTTPS 주소로 307 → 화면 200.
- HTTPS 인증서 검증 성공(인증서 검사 비활성화 사용 안 함).
- 접속 키 없는 API는 401, 유효한 접속 키와 허용 Origin은 200, 다른 Origin은 403.
- `wss://YOUR_DEVICE.YOUR_TAILNET.ts.net/...`에서 start → 48kHz/150ms 무음 PCM → stop 완료.
- 화자 모델 미준비로 해당 무음 transport 시험은 PARTIAL로 종료했으며, 임시 시험 기록은 삭제했습니다.
- 백엔드 리스너는 `127.0.0.1:8765`를 유지합니다. Tailscale TCP 8765와 HTTPS 443을 Serve로 공개했습니다. Funnel 설정은 없습니다.

검증은 서버 Mac에서 자신의 Tailscale IP/도메인을 경유한 결과입니다. 다른 기기, 네트워크별 접근 제어, 실제 원격 마이크 녹음은 미검증입니다. [설정 안내](hf-and-tailscale.md).


## HF 준비 후 전체 파이프라인 — 2026-09-09 UTC

사용자가 Community-1 접근 권한을 준비하고 다운로드를 완료했습니다. manifest에 모델 commit `3533c8cf8e369892e6b79ff1bf80f7b0286a54ee`가 기록되어 있습니다.

- OS 네트워크 차단 상태에서 Community-1 CPU 로드 및 추론 성공. 로드 16.390초, 5.820초 합성 음성 추론 0.689초, 결과 화자 1명. 짧은 샘플에서 pooling 표준편차 관련 UserWarning이 있었지만 추론은 완료했습니다.
- STT 서버가 실행되어 있지 않아 다시 시작했습니다. 현재 Whisper/Community-1/Silero가 모두 ready입니다.
- Tailscale HTTPS API의 실제 파일 업로드 → Whisper 전사 → Community-1 화자 분석 → 대본 결합이 **COMPLETED**로 끝났습니다. 화자 A 배정과 assigned 상태를 확인했습니다.
- 전체 파일 처리 2.627초: 전처리 0.135초, ASR 1.598초, 화자 분석 0.889초, 결합 0.00049초. RTF 0.451. 앱 결과의 warnings는 빈 목록입니다.

이는 Yuna 1인 합성 음성 시험이며 실제 2~3인/8인 분리 성능이나 실제 마이크 품질 검증은 아닙니다. 다음 검증은 실제 다인 파일과 원격 마이크 입력입니다.

원시 결과: [실제 화자 엔진 오프라인 검증](real-diarization-smoke.json), [전체 파일 파이프라인](full-pipeline-smoke.json).


## 접속 502 복구와 상시 실행 검증 — 2026-09-09 UTC

Tailscale Serve는 정상이나 임시 STT 프로세스가 종료되어 loopback 연결 실패와 HTTPS 502가 발생한 것을 확인했습니다. macOS LaunchAgent `com.meetingbot.stt`를 등록하고 실행본을 `~/Library/Application Support/Meetingbot`에 배치했습니다. Documents에서 실행한 초기 LaunchAgent는 Python 초기 파일 열기 단계에서 멈춰 표준 앱 데이터 위치로 변경했습니다. 기존 `.runtime` 데이터를 이동하고 소스 위치에 링크를 만들어 대본·모델·인증 키를 유지했습니다.

- HTTPS 화면 200, IP→HTTPS 이동 후 200, 미인증 API 401 확인.
- LaunchAgent에 SIGTERM을 보내 자동 재시작 검증: PID 34039 → 34091, Whisper/Community-1/Silero 모두 ready로 복구.
- 실행 프로세스의 부모는 launchd(PID 1)이며 Codex 임시 터미널 프로세스가 아닙니다.
- LaunchAgent의 RunAtLoad/KeepAlive 활성화. 실제 로그아웃·재로그인은 시험하지 않았습니다. Mac 잠자기와 네트워크 상태에 따른 원격 접속 시험은 별도입니다.
