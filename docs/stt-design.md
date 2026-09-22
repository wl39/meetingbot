# 회의봇 STT 테스트 모듈 설계

- 버전: 제안 v0.1
- 작성일: 2026-09-09
- 상태: 설계 문서. 실제 모델 설치, 구현, Mac mini 성능 측정은 수행하지 않음.
- 기준 자료: 사용자가 제공한 「다중 화자 회의 보조 AI 구현」의 공통 스택, 음성 어댑터, UtteranceEvent, 로컬 처리 원칙.
- 이번 변경: 전체 회의봇보다 STT 테스트를 먼저 만든다. RAG / STT / 관리 모듈은 독립 개발하고 공통 계약을 통해 합친다.

## 1. 목표와 범위

두 페이지를 제공한다.

1. 파일 전사: 음성 파일 업로드 → 텍스트 전사 → 화자별 대본 → 수정 및 내보내기.
2. 실시간 전사: 마이크 입력 → 갱신되는 자막 → 지연된 화자 표시 → 종료 시 화자 결과 재정리.

이번의 화자 분리는 같은 세션 안에서 “누가 언제 말했는지”를 A/B/C로 구분하는 diarization이다. 실명 자동 식별, 세션을 넘는 화자 인식, 겹친 음성을 각각의 깨끗한 음성으로 복원하는 source separation은 구현 범위가 아니다. WhisperX도 겹친 발화와 화자 분리의 한계를 명시한다.[R3]

실시간 페이지에서 화자 분리를 생략하지 않는다. 다만 단어가 표시되는 시점과 화자가 배정되는 시점을 분리한다. 화자 정보는 잠정 결과이며 뒤늦게 바뀔 수 있다.

초기 제안 제한은 다음과 같다. 제품의 성능 보장이 아니라 테스트를 단순하게 만드는 설정이다.

| 항목 | 제안 기본값 |
|---|---|
| 사용자 | 로컬 단일 사용자 |
| 실행 환경 | macOS / Apple Silicon 우선, 실제 칩·메모리 감지 |
| 입력 채널 | 공용 마이크 하나, 1개 실시간 세션 |
| 언어 | 한국어, `language=ko` |
| 파일 입력 | WAV, MP3, M4A, FLAC |
| 파일 상한 | 100MB 및 10분, 모두 만족해야 함 |
| 실시간 세션 상한 | 5분 |
| 화자 수 | 자동 또는 사용자가 알고 있는 인원수 지정; 자동은 1~8 범위 후보 |
| 동시 작업 | 파일 전사와 실시간 세션을 동시에 실행하지 않음 |
| 원음 영구 보관 | 기본 비활성화 |

초기에는 다중 사용자 계정, RAG 검색, LLM 교정·요약, TTS, 시스템 오디오 캡처, 장시간 회의, 온라인 화자 임베딩 추적, 세션 간 성문 등록을 만들지 않는다.

## 2. 기술 선택

| 역할 | 선택 | 설계상 이유 |
|---|---|---|
| 프론트엔드 | React + TypeScript + Vite | 기존 회의봇 화면에 붙일 기능 모듈로 구현 |
| 백엔드 | FastAPI + Pydantic | HTTP, WebSocket, 검증된 이벤트 계약 |
| STT | `mlx-whisper` 어댑터 | 기존 Apple Silicon 방향 유지 |
| STT 모델 | Whisper 다국어 small부터 시작, large-v3-turbo는 비교 후보 | 속도·정확도를 실제 환경에서 비교 후 변경 |
| 화자 분리 | `pyannote.audio` + `speaker-diarization-community-1` | 로컬 배치 화자 분리 |
| 음성 활동 감지 | Silero VAD, ONNX 경로 | 발화 시작·끝 판단 |
| 오디오 전처리 | FFmpeg + 스트리밍 리샘플러 | 파일 디코딩, 공통 시간축 |
| 저장 | SQLite WAL + 필요한 임시 파일 | 외부 서비스 의존성 최소화 |
| 실행 | uv, 네이티브 Python, 별도 추론 워커 | API 이벤트 루프와 추론 분리 |

MLX Whisper는 Whisper의 MLX 구현이고 단어 단위 타임스탬프 출력을 제공한다.[R1] WhisperX는 별도의 기본 인식 모델이라기보다 전사·강제 정렬·화자 분리를 묶은 파이프라인이며, 공식 README는 macOS용 CPU 실행 예제를 제공한다.[R3] 그러므로 이번에는 MLX Whisper와 화자 분리를 각각 교체 가능한 어댑터로 둔다. WhisperX가 정확도가 낮다고 단정하는 선택은 아니다.

Community-1은 모델 접근 조건 동의와 Hugging Face 토큰을 통한 준비가 필요하며, 모델을 내려받은 뒤 로컬 실행을 지원한다.[R2] HF 토큰은 서버 설정에서만 읽는다. 모델·코드의 라이선스를 구분해 배포 문서에 기록한다. 화자 분리는 CPU부터 검증하고 MPS 지원·성능은 실제 설치 조합으로 검사하기 전까지 보장하지 않는다.

`PYANNOTE_METRICS_ENABLED=0`을 지정해 pyannote 사용량 지표 전송을 비활성화한다.[R4] 모델 다운로드 과정과 추론 과정의 네트워크 사용을 구분하고, 준비 완료 후 네트워크를 차단한 테스트로 외부 의존 여부를 확인한다. STT 테스트 경로는 CLIProxyAPI, LangChain, LLM API를 호출하지 않는다.

## 3. 모듈 경계

```text
STT 화면
  ├─ 파일 전사
  └─ 실시간 전사
       │ HTTP / WebSocket
       ▼
STT 모듈
  ├─ 입력 검증·오디오 전처리
  ├─ 파일 처리 컨트롤러
  ├─ 실시간 처리 컨트롤러
  ├─ ASR 어댑터
  ├─ 화자 분리 어댑터
  ├─ 화자 ID 매핑·텍스트 결합
  └─ 전사 저장·UtteranceEvent 발행
       │
       ▼
회의 컨트롤러 — 나중에 연결
  ├─ RAG 모듈에 검색 요청
  └─ 관리 모듈이 정한 회의·사용자 범위 적용
```

STT는 RAG 내부 함수나 관리 DB에 직접 접근하지 않는다. RAG와 관리 기능이 없는 상태에서도 STT만 실행 가능해야 한다.

독립 모듈을 처음부터 세 개의 분산 서비스로 만들 필요는 없다. 하나의 저장소에서 라우터·도메인·엔진 의존성을 분리하고, 나중에 통합 FastAPI 앱에 STT 라우터를 장착하는 방식을 기본으로 한다.

외부 엔진의 원시 반환 형식은 어댑터 안에서 공통 모델로 변환한다.

```text
SpeechToText.transcribe(audio, options)
  → ASRResult(segments, words, language, diagnostics)

SpeakerAttribution.diarize(audio, options)
  → DiarizationResult(turns, overlap_regions, diagnostics)

TranscriptAssembler.combine(asr_result, diarization_result)
  → UtteranceEvent[]
```

위 이름은 제안 인터페이스이며 특정 라이브러리의 실제 API 이름이 아니다.

## 4. 파일 전사

### 화면

상단에는 파일 선택, 모델, 언어, 화자 수, 시작·취소를 둔다. 하단에는 단계별 처리 상태와 화자별 대본을 표시한다.

```text
파일: sample-meeting.m4a
모델: Whisper small    언어: 한국어    화자 수: 자동
[전사 시작] [취소]

현재 단계: 화자 분석 중

00:02.4–00:05.8  화자 A
오늘은 로그인 기능부터 확인하겠습니다.

00:06.1–00:10.2  화자 B
QA에서 발견된 오류부터 볼까요?

[텍스트 수정] [화자 수정] [TXT / SRT / JSON 내보내기]
```

### 처리 흐름

```text
업로드·형식·용량 검증
→ 임시 파일 및 Job 등록
→ HTTP 202 반환
→ 워커가 길이·디코딩 가능 여부 검증
→ 공통 16kHz mono 오디오 생성
→ Whisper 전사와 단어 시간 추출
→ 전체 파일 화자 분리
→ 동일 시간축에서 단어와 화자 구간 결합
→ 수정 가능한 대본 저장
→ 임시 오디오 삭제
```

화자가 바뀌면 같은 ASR 문장 안에서도 대본을 나눈다. 단어와 화자 구간의 시간 겹침을 기준으로 배정하고, 근거가 부족하면 미확정으로 남긴다. 겹친 발화 구간은 별도 표시하며 한 화자의 문장으로 완벽히 복원되었다고 표현하지 않는다.

Whisper 자체 단어 시간은 강제 정렬 결과와 동일하다고 취급하지 않는다. 초기에는 이 시간으로 결합을 검증하고, 한국어 시간 정밀도 문제가 확인될 때에만 정렬 어댑터를 추가 검토한다.

VAD로 선택한 구간을 전사하더라도 원본 시간 오프셋을 보존한다. 무음을 제거한 파형을 이어 붙인 시간을 그대로 원본 시간으로 쓰지 않는다. 다중 채널 파일은 초기에는 mono로 처리하되 채널 수와 변환 사실을 기록한다. 참가자별 채널 입력은 별도 확장으로 둔다.

전사 성공·화자 분리 실패는 `PARTIAL`로 표시한다. 자막을 버리거나 임의 화자 번호를 붙이지 않는다. 일반 로그에는 발언 전문을 남기지 않는다.

## 5. 실시간 전사

### 브라우저 오디오

```text
getUserMedia
→ AudioWorklet
→ 실제 AudioContext 샘플레이트의 mono PCM
→ 100~200ms 단위 이진 WebSocket 프레임
→ 서버의 상태 유지형 리샘플러
→ 16kHz 오디오 시간축
```

AudioWorklet은 별도 오디오 스레드에서 사용자 오디오 처리를 지원한다.[R6] 샘플레이트를 16kHz라고 가정하지 말고 실제 값을 핸드셰이크에 전달한다. 프레임마다 리샘플러를 초기화하지 않는다.

실시간 전사 입력은 `MediaRecorder`가 만든 조각을 매번 독립 음성 파일처럼 디코딩하는 방식으로 만들지 않는다. 표준상 개별 Blob의 독립 재생 가능성은 보장되지 않는다.[R7] 파일 입력과 실시간 입력을 디코딩 계층부터 구분한다.

오디오 프레임에는 세션, 입력 스트림 ID, 순서 번호, 시작 샘플 번호, 샘플 수, 실제 샘플레이트를 연결한다. 시간은 서버에 도착한 시각이 아니라 샘플 위치로 계산한다. 누락은 조용히 없애지 않고 `audio.gap` 이벤트와 대본 경고로 남긴다.

### A. 빠른 텍스트 경로

```text
오디오 수신
→ 짧은 ASR 버퍼 + 세션 누적 버퍼
→ VAD
→ 약 2초 주기로 최근 발화 재전사
→ partial 자막 갱신
→ 침묵 감지 또는 안정화 규칙 충족
→ stable 발언
```

Whisper의 기본 `transcribe()`는 파일을 슬라이딩 윈도로 처리한다. 이 설계의 실시간성은 모델의 특별한 스트리밍 API가 아니라 버퍼링·반복 추론·결과 병합으로 구현한다.[R5]

제안 시작값:

| 설정 | 값 |
|---|---|
| 전송 프레임 | 100~200ms |
| ASR 재평가 주기 | 2초 |
| ASR 문맥 창 | 최근 10~15초 |
| 발화 종료 침묵 | 약 700ms |
| 다음 창과 겹칠 구간 | 약 1초 |
| VAD 앞부분 보존 | 약 300ms |

위 숫자는 추론 지연 보장이 아니다. 짧은 “네”, “아니요”도 테스트에 포함하고 최소 발화 길이로 일괄 삭제하지 않는다. 장문 발화는 무한 대기하지 않도록 시간·단어 경계에서 나눈다.

겹치는 오디오 창의 결과는 타임스탬프와 텍스트 정렬로 병합한다. 단순한 문자열 접두사 제거는 쓰지 않는다. 같은 말을 실제로 두 번 했을 때 한 번으로 잘못 줄이지 않아야 한다. 침묵 동안 모델을 무조건 반복 호출하지 않는다.

`stable`은 변경이 절대 없는 정답이라는 뜻이 아니라 현재 후속 처리에 사용할 수 있는 안정화 결과라는 뜻이다. 나중에 더 높은 revision으로 수정될 수 있다.

### B. 지연된 화자 경로

단순한 초기 테스트에서는 **20초마다 세션 시작부터 현재까지의 누적 음성을 배치 재분석**한다. 세션 상한을 5분으로 제한하는 이유가 여기에 있다. 짧은 창만 분석하면서 화자 임베딩을 별도로 추적하는 온라인 시스템은 이번에 만들지 않는다.

```text
세션 누적 오디오
→ 20초 주기 화자 분석 요청
→ 전체 누적 구간의 화자 결과
→ 기존 결과와 공통 시간 구간 비교
→ 세션 내부의 고정 화자 ID로 재매핑
→ 이미 표시한 발언의 화자 정보 수정
```

매 분석의 `SPEAKER_00`을 기존 화면의 화자 A로 그대로 간주하지 않는다. 이전 화자와 새 클러스터 사이에 겹친 비중첩 발화 시간을 계산해 매칭하고, 근거가 약하거나 분할·병합이 모호하면 미확정 또는 수정 상태로 남긴다. 새 ID는 충분한 발화 근거가 생겼을 때만 만든다.

이 방식은 구현을 줄이는 대신 세션이 길어질수록 반복 계산량이 늘어난다. 장시간 회의용 최종 구조가 아니다. 같은 워커에 오래된 누적 분석 요청을 계속 쌓지 않고, 실행 중 작업 뒤의 대기 요청은 최신 스냅샷 하나로 합친다. 오래된 revision 결과가 최신 결과를 덮어쓰지 못하게 한다.

실시간 화면은 “화자 분석 지연”과 마지막 분석 구간을 보여준다. 처리가 밀리면 화자 표시만 늦게 갱신하고 음성 수신과 자막 경로를 막지 않는다. 주기보다 분석 시간이 길어져도 실행 중 추론을 즉시 선점할 수 있다고 가정하지 않는다.

### 종료

```text
중지 요청
→ 마지막 오디오 순서 번호 확인
→ 남은 오디오 및 마지막 발화 전사
→ 누적 음성의 마지막 화자 분석
→ 화자·대본 병합 및 revision 갱신
→ COMPLETED 또는 PARTIAL
→ 메모리 오디오 해제
```

화면에는 중지 직후 `FINALIZING`을 표시한다. 종료 시 분석도 모델 추정 결과이지 실제 인물 확인은 아니다. 실명은 사용자가 별도로 붙인다.

### 화면 예

```text
입력: Mac mini 마이크    모델 준비됨
[시작] [중지]    경과 01:24    음성 입력 감지 중

00:08.1  화자 미확정  / 임시 자막
이번 배포 일정은...

00:12.4  화자 A       / 잠정 화자
금요일까지 확인하겠습니다.

최근 오디오 처리 지연: 실제 측정값
최근 화자 분석 범위: 00:00~01:00
```

## 6. 공통 이벤트와 저장 모델

기존 문서의 `UtteranceEvent` 의미를 유지한다. 독립 STT에는 `session_id`를 필수로 두고 `meeting_id`는 nullable로 둔다. 통합 시 관리·회의 컨트롤러가 검증한 회의 ID를 연결한다.

```json
{
  "schema_version": 1,
  "event_id": "evt_01",
  "session_id": "stt_session_01",
  "meeting_id": null,
  "utterance_id": "utt_01",
  "revision": 3,
  "speaker_id": "spk_01",
  "speaker_status": "provisional",
  "start_ms": 12400,
  "end_ms": 15100,
  "text": "금요일까지 확인하겠습니다.",
  "status": "stable",
  "source": "audio",
  "input_mode": "microphone",
  "addressed_to_ai": false
}
```

텍스트 상태:

```text
partial → stable → corrected
                  ↘ retracted
```

화자 상태는 별도다.

```text
unknown / provisional / assigned / manual
```

`assigned`는 해당 분석 작업의 모델 배정 완료를 뜻한다. 신원 인증이나 완벽한 정확도를 뜻하지 않는다. 화자 ID는 세션 범위에서만 의미를 가진다. 표시 이름은 별도 Speaker 레코드에 저장한다.

중요 계약:

- 같은 `event_id`는 한 번만 처리한다.
- 같은 `utterance_id`에서 revision은 단조 증가한다. 늦게 도착한 낮은 revision을 폐기한다.
- 텍스트 또는 화자가 바뀌면 새 revision을 기록한다. 변경 필드를 함께 전달하거나 소비자가 이전 값과 비교할 수 있게 한다.
- 발언을 분할·병합해야 하면 기존 발언을 retract하고 새 발언에 `replaces_utterance_ids`를 연결한다.
- 사용자 교정은 기준 revision을 검사해 충돌을 알리고, 모델의 후속 결과가 수동 수정 필드를 덮어쓰지 못하게 한다.
- 표시용 최신 상태와 변경 이벤트 이력을 분리한다. 모든 중간 partial을 영구 저장할 필요는 없지만 stable·corrected·retracted 이력은 보존한다.
- 향후 RAG는 기본적으로 stable·corrected·retracted를 소비한다. 화자 이름만 바뀐 경우 검색을 다시 실행할지는 컨트롤러에서 구분한다.
- STT는 AI 대상 질문 여부를 자체 추정하지 않는다. 기본 `addressed_to_ai=false`이고 버튼·호출 처리 계층에서 결정한다.

최소 저장 단위는 Session, Job, Speaker, Utterance, UtteranceRevision/Event다. 모델 ID·정확한 모델 revision·설정·실행 환경·측정값은 Session/Job의 설정 스냅샷으로 남긴다.

## 7. API

아래는 초기 제안 계약이다. 파일명이나 라이브러리 원시 구조는 계약에 노출하지 않는다.

| 방식 | 경로 | 역할 |
|---|---|---|
| POST | `/api/stt/files` | 파일 업로드, session/job 등록, 202 반환 |
| GET | `/api/stt/jobs/{job_id}` | 단계·진행·오류 조회 |
| POST | `/api/stt/sessions` | 실시간 세션 생성 |
| WS | `/api/stt/sessions/{session_id}/stream` | 오디오 입력, 제어, 이벤트·측정값 |
| GET | `/api/stt/sessions/{session_id}` | 최신 대본·화자·상태 스냅샷 |
| PATCH | `/api/stt/sessions/{session_id}/utterances/{utterance_id}` | 텍스트·화자 수동 수정 |
| PATCH | `/api/stt/sessions/{session_id}/speakers/{speaker_id}` | 표시 이름 수정 |
| GET | `/api/stt/sessions/{session_id}/export?format=txt` | TXT/SRT/JSON 내보내기 |
| DELETE | `/api/stt/sessions/{session_id}` | 취소·기록·관리 대상 원음 삭제 |
| GET | `/api/stt/health` | 모델·실행 장치·다운로드·준비 상태 |

WebSocket 제어 메시지는 start/stop/ack/error를 포함한다. stop에는 마지막 audio sequence를 넣어 해당 프레임까지 수신했는지 확인한다. 연결이 끊겼을 때는 세션을 `INTERRUPTED`로 표시하고 수신 완료된 범위만 처리한다. 첫 버전에서는 자동 녹음 재개를 지원하지 않는다. 재연결 시 스냅샷을 다시 읽을 수는 있어야 한다.

파일 상태는 QUEUED → PREPROCESSING → TRANSCRIBING → DIARIZING → MERGING → COMPLETED를 기본으로 하고 PARTIAL/FAILED/CANCELLED를 구분한다. 실시간은 CREATED → RECORDING → FINALIZING → COMPLETED와 INTERRUPTED/PARTIAL/FAILED를 구분한다.

## 8. 실행·자원·안전

추론은 FastAPI 요청·WebSocket 이벤트 루프에서 직접 수행하지 않는다. 기본 구조는 API 프로세스, ASR 워커 1개, 화자 워커 1개다. 모델은 워커 시작 후 준비하고 요청마다 다시 로드하지 않는다. 모델 준비 전에는 시작 버튼 대신 준비 상태를 표시한다.

SQLite 작업 기록과 제한된 로컬 큐를 사용한다. 파일 분석 중 실시간 시작은 대기 또는 명시적 취소로 안내한다. 이미 실행 중인 추론을 즉시 정지할 수 있다는 전제로 UI를 만들지 않는다. 새 서비스 시작 시 남아 있는 RUNNING 작업은 중단 상태로 바꾸고 재시도 가능 여부를 표시한다.

수신 오디오를 임의로 버려 지연을 숨기지 않는다. ASR의 오래된 partial 재계산 요청은 합칠 수 있지만 처리할 원음은 유지한다. 버퍼 상한을 넘으면 명시적으로 중지하거나 누락을 표시한다. 끝없는 작업 큐와 메모리 증가는 허용하지 않는다.

실시간 음성은 기본적으로 5분 이내 세션의 메모리에만 보유하고 마지막 처리 뒤 해제한다. 입력 파일은 처리 중 임시 디스크 저장이 필요하며 성공·실패·취소 시 정리한다. 이것을 “파일을 서버에 전혀 저장하지 않는다”고 표시하지 않는다. 음성 보관 옵션을 사용자가 켠 경우만 영구 원음을 저장하고, 재생·재처리와 삭제를 제공한다. 원음 보관을 끈 기록에는 나중의 원음 재생·재처리가 불가능함을 표시한다.

localhost에만 바인딩한다. 브라우저는 명시적 마이크 권한과 안전한 실행 문맥이 필요하다.[R8] CORS와 WebSocket Origin을 허용된 로컬 프론트엔드로 제한하고 쓰기 API·WebSocket 세션에 로컬 인증/세션 검증을 적용한다. LAN 공개는 초기 범위에서 제외한다.

FFmpeg 호출은 임의 셸 명령 조합이 아니라 검증된 인자 배열로 수행한다. 서버가 생성한 파일명과 관리 디렉터리만 사용한다. 경로 탈출·무한 디코딩·메모리 폭증을 크기·길이·시간 제한으로 차단한다. 삭제·취소 후 늦게 도착한 워커 결과가 기록을 되살리지 못하도록 작업 generation을 검사한다.

## 9. 코드 구조 제안

```text
meetingbot/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ contracts/
│  │  │  └─ utterance.py
│  │  └─ modules/
│  │     └─ stt/
│  │        ├─ router.py
│  │        ├─ schemas.py
│  │        ├─ settings.py
│  │        ├─ repository.py
│  │        ├─ file_service.py
│  │        ├─ live_service.py
│  │        ├─ audio.py
│  │        ├─ transcript_assembler.py
│  │        ├─ speaker_mapper.py
│  │        ├─ workers.py
│  │        └─ engines/
│  │           ├─ base.py
│  │           ├─ mlx_whisper_engine.py
│  │           ├─ pyannote_engine.py
│  │           └─ silero_vad.py
│  ├─ tests/
│  ├─ pyproject.toml
│  └─ uv.lock
├─ frontend/
│  └─ src/features/stt/
│     ├─ FileTranscriptionPage.tsx
│     ├─ LiveTranscriptionPage.tsx
│     ├─ TranscriptView.tsx
│     ├─ SpeakerEditor.tsx
│     ├─ audio-worklet.ts
│     └─ api.ts
├─ docs/
│  ├─ stt-design.md
│  ├─ stt-test-results.md
│  └─ stt-limitations.md
└─ .env.example
```

`contracts`에는 공통 데이터만 두고 MLX·PyTorch·pyannote를 import하지 않는다. 무거운 음성 의존성은 선택 설치 그룹으로 분리한다. 테스트에는 fake 어댑터를 사용하되 실제 모델 검증과 별도 표시한다.

## 10. 개발 순서와 완료 기준

### 단계 1: 모델 스모크 테스트

2인 한국어 짧은 파일로 실제 MLX 전사, 단어 시간, pyannote 분리, 결합 결과를 확인한다. HF 접근·모델 준비·CPU 화자 분석을 먼저 검사한다. UI부터 만들고 모델 실행 실패를 뒤늦게 발견하지 않는다.

### 단계 2: 파일 전사 수직 구현

업로드 → 작업 상태 → 대본 → 수동 수정 → JSON/TXT/SRT까지 구현한다. 두 사람이 번갈아 말하는 파일의 화자 전환과 타임스탬프를 사람이 확인한다.

### 단계 3: 실시간 자막

PCM 스트림, VAD, partial/stable, 짧은 발화, 창 경계 중복 제거, 중지 시 마지막 단어 처리를 구현한다. 이 단계만 완료해서 화자 분리 포함 MVP 전체를 완료했다고 보고하지 않는다.

### 단계 4: 지연 화자 분리

누적 음성 재분석, 세션 화자 ID 매핑, 기존 발언 수정, 마지막 분석을 연결한다. 화자 번호가 바뀌는 배치 결과를 인위적으로 넣어 UI의 화자 A/B가 뒤집히지 않는지 검사한다.

### 단계 5: 실패·측정·통합 계약

연결 종료, 모델 누락, 디코딩 오류, 중복 이벤트, revision 역전, 작업 취소, 화자 실패, 원음 삭제를 테스트한다. STT 결과 JSON을 가짜 회의 컨트롤러에 재생해 RAG 없는 환경에서 계약을 검사한다.

### 최소 테스트 세트

| 사례 | 확인할 것 |
|---|---|
| 1인 한국어, 1분 | 기본 인식과 불필요한 화자 증가 |
| 2~3인 번갈아 대화 | 텍스트·화자 대응, 인원수 추정 |
| 짧은 “네/아니요” | VAD 삭제와 화자 미확정 처리 |
| 숫자·영문 기술어 | 인식 오류와 수동 교정 |
| 한 화자의 장문 발화 | 침묵 없이도 자막 진행 |
| 무음·키보드 소음 | 허위 자막과 불필요한 호출 |
| 서로 겹쳐 말하기 | 완전 분리를 주장하지 않고 경고 표시 |
| 오래 쉬었다 다시 말하기 | 같은 세션 화자 ID 유지 여부 |
| 브라우저 연결 종료 | 수신 완료 구간과 누락 표시 |
| 화자 엔진 실패 | 텍스트 보존, PARTIAL과 미확정 화자 |
| 수정 후 늦은 결과 | 수동 교정·최신 revision 보호 |
| 8인 샘플 | 확장 검증; 테스트 전에는 지원 성능을 보장하지 않음 |

### 측정

파일은 전체 시간, 전사 시간, 화자 분석 시간, 결합 시간, RTF를 나누어 기록한다. 실시간은 첫 자막 지연, stable 지연, 화자 배정 지연, 큐 대기, 처리 완료 오디오 위치, 입력 대비 밀린 시간, 메모리를 기록한다.

짧은 문맥 창을 겹쳐 재분석하므로 단일 추론의 RTF가 1 미만이라는 이유만으로 실시간을 유지한다고 판단하지 않는다. 입력이 계속 들어오는 동안 대기량이 누적되는지 직접 측정한다.

한국어 전사는 정답 대본과 비교해 CER 등을 기록하되 띄어쓰기·문장부호 정규화 규칙을 고정한다. 화자 분리는 정답 화자 구간이 있는 샘플에서 DER 또는 명시한 수동 오류 집계를 기록한다. 모델 다운로드·첫 로드·워밍업과 평상시 추론 시간은 구분한다.

테스트 문서에는 실제 실행, 모의 실행, 미실행을 분리해 적는다. 특정 Mac mini 칩이나 8인 음성 성능을 측정 없이 보장하지 않는다.

## 11. 이후 확장

이번 버전의 누적 음성 반복 분석은 짧은 테스트용이다. 장시간 회의에서는 최근 구간 분석과 세션별 화자 임베딩 추적, 온라인 클러스터링 등을 별도로 설계해야 한다. 교체 대상은 주로 `SpeakerAttribution`과 `speaker_mapper`이며, 화면·UtteranceEvent·파일 전사·RAG 계약은 유지하는 것이 목표다.

최종 통합 시에는 관리 모듈이 검증된 meeting_id와 설정을 제공하고, STT가 이벤트를 발행하며, 회의 컨트롤러가 필요한 이벤트를 RAG에 연결한다. STT 자체에 문서 검색이나 언어모델 응답 생성을 추가하지 않는다.

## 참고 자료

설계상의 주기·상한·폴더 구조·이벤트 확장은 이 문서의 제안이다. 다음 링크는 라이브러리 동작·인터페이스·제약 확인에 사용한 공식 문서다. 정확한 패키지 버전과 모델 commit은 구현 환경에서 설치·실행 검증 후 잠금 파일과 설정 스냅샷에 고정한다.

- [R1] MLX Whisper README: https://github.com/ml-explore/mlx-examples/blob/main/whisper/README.md
- [R2] pyannote Community-1 모델 카드: https://huggingface.co/pyannote/speaker-diarization-community-1
- [R3] WhisperX README: https://github.com/m-bain/whisperX
- [R4] pyannote.audio README 및 telemetry 설정: https://github.com/pyannote/pyannote-audio
- [R5] OpenAI Whisper README: https://github.com/openai/whisper
- [R6] MDN AudioWorklet: https://developer.mozilla.org/en-US/docs/Web/API/AudioWorklet
- [R7] W3C MediaStream Recording: https://www.w3.org/TR/mediastream-recording/
- [R8] MDN getUserMedia: https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia
- [R9] Silero VAD README: https://github.com/snakers4/silero-vad

Silero VAD의 지원 샘플레이트와 ONNX 경로는 [R9]를 기준으로 확인한다. 이 문서의 제안 시간값을 해당 라이브러리의 기본값이라고 해석하지 않는다.
