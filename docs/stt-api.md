# STT API v1

모든 `/api/stt/*` HTTP 요청은 `Authorization: Bearer <local-token>`을 요구합니다. 로컬 토큰은 `.runtime/local-token`에 권한 0600으로 저장합니다. 허용 Origin 밖의 요청과 localhost 이외의 Host를 거절합니다. 기본 서버는 127.0.0.1:8765에만 바인딩합니다.

## HTTP

| 메서드 | 경로 (`/api/stt` 뒤) | 입력/결과 |
|---|---|---|
| GET | `/health` | 실제/모의 모드, 워커 준비, 모델 commit, 환경, 한도 |
| POST | `/files` | multipart `file`, JSON 문자열 `options` → 202 session_id/job_id |
| GET | `/jobs/{id}` | 단계·에러·측정값 |
| POST | `/sessions` | options JSON → 마이크 세션 CREATED |
| GET | `/sessions` | 최근 기록 목록 |
| GET | `/sessions/{id}` | snapshot_revision 포함 최신 상태 |
| PATCH | `/sessions/{id}/utterances/{utterance_id}` | base_revision, 변경할 text/speaker_id만 전달 |
| POST | `/sessions/{id}/speakers` | name → 사용자가 만든 화자 ID |
| PATCH | `/sessions/{id}/speakers/{speaker_id}` | 표시 이름 수정 |
| GET | `/sessions/{id}/events` | stable/corrected/retracted 변경 이력 |
| GET | `/sessions/{id}/export?format=txt\|srt\|json&view=utterance\|script` | UTF-8 내보내기. `view` 기본값은 `utterance` |
| GET | `/sessions/{id}/export/preview?format=txt\|srt\|json&view=utterance\|script` | 선택한 형식/보기의 첫 2개 항목 미리보기. `{content, total_items, preview_items}` 반환 |
| GET | `/sessions/{id}/audio` | 보관을 켠 세션만 PCM WAV 재생 |
| POST | `/sessions/{id}/reprocess` | 보관된 원음으로 새 파일 작업 생성 |
| DELETE | `/sessions/{id}` | 활성 작업 무효화, 기록·이력·관리 원음 삭제 |

옵션: `{"model":"small","language":"ko","num_speakers":null,"retain_audio":false}`. 알려진 화자 수는 1~8 정수입니다. `large-v3-turbo`는 선택 설치 모델입니다. 세션 삭제가 취소 역할도 하므로 취소하면 대본도 삭제합니다. 실행 중인 추론이 끝나기 전에는 다음 작업의 동시 실행 잠금을 유지합니다.

### 대본 내보내기와 미리보기

`view=utterance`는 원래 발화 단위를 유지합니다. `view=script`는 대본 보기와 같이 시간순으로 정렬한 뒤, 겹치지 않고 간격이 3초 이하인 같은 화자의 발화를 묶습니다. 같은 화자 사이의 미확정 발화는 전체 길이가 2초 이하이고 수동 화자 지정이나 겹침이 없을 때만 함께 묶습니다. 원본 텍스트·화자 지정·이력은 변경하지 않습니다.

TXT/SRT는 선택한 보기의 단위별 시간과 화자, 텍스트를 내보내며, 묶음에 미확정 발화가 포함되면 표시합니다. 기본 JSON은 기존 세션·`utterances`·`events` 구조를 그대로 유지합니다. 대본 JSON은 여기에 `export_view: "script"`와 `script_blocks`를 추가합니다. 각 묶음은 첫 원본의 `utterance_id`, `start_ms`, `end_ms`, `speaker_id`, `speaker_name`, `text`, `source_utterance_ids`, `includesUnknown`, `overlap`을 포함합니다.

미리보기는 철회된 발화를 제외한 선택 단위의 첫 2개를 보여 주며, 각 텍스트는 생략 부호를 포함해 최대 240자입니다. `total_items`는 선택한 보기의 전체 항목 수이고 `preview_items`는 실제 미리보기 항목 수입니다. JSON 미리보기는 항목의 주요 필드만 보여 주는 유효한 JSON이며 세션 메타데이터, 변경 이력, 단어 배열을 포함하지 않습니다.

## WebSocket

`/sessions/{id}/stream`, subprotocols `['stt','stt.<local-token>']`. 서버는 `stt`를 선택합니다. 인증 키를 URL query에 넣지 않습니다.

첫 메시지:

```json
{"type":"start","stream_id":"unique-stream","sample_rate":48000,"channels":1,"encoding":"f32le"}
```

세션·스트림·샘플레이트는 이 연결에 고정합니다. 이후 오디오 프레임은 little endian 이진 형식입니다.

| 오프셋 | 형식 | 의미 |
|---|---|---|
| 0 | uint32 | sequence, 0부터 시작 |
| 4 | uint64 | 입력의 start_sample |
| 12 | uint32 | sample_count |
| 16 | float32 × sample_count | mono PCM -1~1 |

AudioWorklet은 실제 AudioContext 샘플레이트에서 약 150ms를 모아 전송합니다. stop 전에 마지막 짧은 프레임도 flush합니다. 서버는 soxr.ResampleStream 하나를 세션 내내 유지하며 16kHz 시간축으로 변환합니다. sequence/sample 누락은 audio.gap 경고와 명시적 무음 구간으로 보존합니다. 5초보다 긴 단일 누락·역전·잘못된 PCM·5분 상한 초과는 연결을 중단하고 받은 범위를 정리합니다.

중지: `{"type":"stop","last_sequence":N}`. 실제 수신 sequence와 다르면 `STOP_SEQUENCE_MISMATCH`를 반환합니다. 일치하면 FINALIZING → 최종 snapshot → completed. 종료 작업은 소켓이 끊겨도 살아 있는 서비스 작업으로 실행됩니다. 연결 중단은 INTERRUPTED이며 자동 녹음 재개는 없습니다.

서버 메시지: ack, snapshot, audio.gap, error, completed, deleted. snapshot에는 UtteranceEvent 필드가 있는 최신 발언이 포함되며 HTTP events에서 영구 이력을 재생합니다. 개별 utterance delta push 대신 최대 0.5초 간격의 전체 snapshot을 보내는 초기 구현입니다. 프론트엔드는 snapshot_revision이 뒤처진 응답을 폐기합니다.

## 소비자 계약

`schema_version=1`, 세션 필수, meeting_id nullable, `addressed_to_ai=false`. 같은 event_id는 한 번만 처리하고 `(session_id, utterance_id)`의 낮은 revision은 폐기합니다. 분할·병합 시 기존 발언을 retract하고 새 발언에 replaces_utterance_ids를 붙입니다. 모든 partial은 DB 이력에 남기지 않습니다.

수정은 기준 revision이 다르면 409입니다. 수동 텍스트는 자동 화자 변경을 허용하면서 텍스트를 보호하고, 수동 화자는 자동 텍스트 변경을 허용하면서 화자를 보호합니다. 수동 교정 구간 경계는 이후 대본 재조립에서도 유지합니다. 수동 구간 안에서 여러 화자 결과가 충돌하면 자동 화자는 미확정으로 남깁니다.
