# API 계약

실행 서버의 `/openapi.json` 및 `/docs`에서 Pydantic 입력 계약을 확인한다. 모든 데이터 API는 `/api/rag` 아래에서 관리자 Bearer 키 또는 세션 인증을 요구한다. 일반 브라우저에서는 쿠키 세션을 사용하고 변경 요청에 `Origin`과 `X-CSRF-Token`을 보낸다. 원문 경로를 받는 범용 파일 API는 없다.

| 메서드 | 경로 (prefix 생략) | 책임 |
|---|---|---|
| POST | `/auth/login` | `{key}` → 세션 쿠키와 csrf |
| GET / POST | `/auth/session`, `/auth/logout` | 세션 복구 / 철회 |
| GET | `/source-roots` | 허용 루트 id/label, 설정 필요 상태 |
| GET | `/source-roots/{root_id}/entries` | relative_path, cursor, filter; 현재 폴더만 탐색 |
| POST / GET | `/source-previews`, `/source-previews/{job_id}` | 영속 스캔(202) / 상태 |
| GET / POST | `/workspaces` | 목록 / 생성(201) |
| GET / PATCH / DELETE | `/workspaces/{workspace_id}` | 조회 / 이름·설명·승인 / 앱 자료만 삭제 |
| POST | `/workspaces/{workspace_id}/sources` | root_id, relative_path 등록 |
| GET | `/workspaces/{workspace_id}/documents` | 명시 또는 활성 READY revision_id의 파일 manifest |
| GET | `/workspaces/{workspace_id}/revisions` | 버전과 상태 목록 |
| PATCH / DELETE | `/workspaces/{workspace_id}/revisions/{revision_id}` | `{pinned: bool}` 보존 / 보호되지 않은 과거 버전 삭제 |
| POST | `/workspaces/{workspace_id}/index-jobs` | 새 버전 구축(202), 선택 Idempotency-Key 헤더 |
| GET / POST | `/workspaces/{workspace_id}/index-jobs/{job_id}`, `…/{job_id}/cancel` | 상태 / 취소 요청 |
| POST | `/workspaces/{workspace_id}/search` | `{query, revision_id?, top_k?}` 로컬 근거 검색 |
| GET / POST | `/workspaces/{workspace_id}/questions` | 최근 질문 / 비동기 질문 접수 (`202`, `request_id`) |
| GET | `/history/{request_id}` | 계정별 질문 진행 상태 및 최종 결과 (`result.status`) |
| GET | `/workspaces/{workspace_id}/evidence/{evidence_id}?revision_id=…` | 해당 버전의 근거와 원문 snapshot |
| GET / POST | `/diagnostics`, `/diagnostics/llm-check` | 상태 / 합성 입력으로 프록시 모델 목록·호출 진단 |
| GET / PUT | `/settings` | 영속 청킹·검색 설정 / 버전 확인 후 저장 |
| GET / POST | `/embedding`, `/embedding/install` | 임베딩 준비 상태 / 고정 모델 다운로드·재시도(202) |

공간 생성 입력: `{name, description?, root_id?, relative_path?}`. 서버에서는 공간·지식베이스·소스에 별도 UUID를 발급한다. 같은 소스 폴더를 두 공간에 연결해도 문서 내용 캐시를 공유하지 않는다.

검색 응답은 workspace_id, knowledge_base_id, revision_id, access_scope_version, request_id, query, evidence, timings_ms를 포함한다. evidence는 evidence_id, workspace_id, revision_id, document_id, document_version_id, chunk_id, relative_path, title_path, location, text와 표인 경우 구조화 table을 포함한다. evidence_id는 revision ID와 chunk ID 조합이며 경로로 변환하지 않는다.

오류는 `{error_code, message, request_id}`. 미인증 401, 경로·Origin·CSRF·회수된 소스 403, 없는 객체 404, 버전/자료 상태 충돌 409, 길이/형식 422, 자원 제한 429를 사용한다. 명시 과거 버전이 없으면 활성 버전으로 대체하지 않는다.

전송 동의 PATCH는 `{external_llm_approved:true, provider_id:<diagnostics 값>}`이며 전역 허용도 필요하다. 연결 URL 또는 모델 변경 시 provider_id가 바뀌므로 이전 동의가 유효하지 않다. 철회는 `{external_llm_approved:false}`. LLM 상태는 answered / insufficient_evidence / conflicting_evidence / llm_unavailable / aggregation_unsupported다. 프록시 호출을 못 하면 가짜 답변을 생성하지 않는다.


## 청킹·검색 설정과 임베딩 설치

`GET /settings` 응답은 `{version,chunk_tokens,overlap_tokens,top_k,updated_at,limits,reindex_required,workspaces}`다. `workspaces` 항목은 `{workspace_id,name,active_revision_id,chunk_count,requires_reindex,has_source,indexing}`를 포함한다. `chunk_count`는 현재 활성 자료 버전에서 실제 생성된 청크 수다. 직접 입력하는 청크 개수가 아니라 청크 크기와 겹침으로 문서별 생성 개수를 조절한다. 일반적으로 청크를 작게 나누거나 겹침을 늘리면 청크 수가 증가한다. 문서 구조·제목 길이·임베딩 토큰 한도에 따라 실제 결과는 달라진다.

`PUT /settings` 본문은 `{expected_version,chunk_tokens,overlap_tokens,top_k}`다. 청크 크기는 32–400 토큰, 겹침은 0 이상이고 청크 크기보다 작아야 하며, 검색 근거 수는 1–12개다. 정수만 허용하고 알 수 없는 필드는 422로 거절한다. `expected_version`이 현재 값과 다르면 `SETTINGS_VERSION_CONFLICT`(409)를 반환한다. 성공 응답은 GET과 같은 형태다. 저장 전에는 환경 설정을 기본값으로 사용하며 저장 후에는 DB 값이 재시작과 업데이트 후에도 우선 적용된다.

검색 근거 수는 다음 검색·문서 질문부터 적용되며 재색인을 요구하지 않는다. 요청의 `top_k`를 생략하면 저장한 값을 사용하고 명시하면 저장한 값 이하로 제한한다. 검색 결과의 `retrieval_settings_version`으로 적용된 설정 버전을 확인한다. 실시간 회의 검증은 인용 제한 때문에 최대 6개를 유지한다.

청크 크기·겹침 변경은 기존 자료 버전을 재작성하지 않는다. 이전 활성 버전은 검색할 수 있고 `requires_reindex`로 재준비가 필요함을 알린다. `POST /workspaces/{workspace_id}/index-jobs`로 새 자료 버전을 만들고 `GET /workspaces/{workspace_id}/index-jobs/{job_id}`로 진행 상태를 확인한다. 새 READY 버전이 완성되어야 활성 버전이 바뀐다. 대기·진행 중 작업은 생성 시점의 청킹 설정을 끝까지 사용하므로, 그 사이 설정을 다시 바꾸면 작업 완료 후에도 재준비 표시가 남을 수 있다. 다른 청킹 설정의 청크·벡터를 증분 캐시에서 재사용하지 않는다.

`POST /embedding/install`은 서버에 설정된 모델 ID와 고정 revision만 내려받는다. 임의 URL이나 실행 명령은 입력받지 않는다. 시작 응답은 202이며 `GET /embedding`으로 `state`, `error_code`, `installing`, `model`, `revision`, `device`를 확인한다. `DOWNLOADING` 중에는 같은 설치를 중복 실행하지 않는다. 성공하면 `READY`, 실패하면 `NOT_READY`와 안전한 오류 코드를 표시하고 같은 API로 재시도할 수 있다. 실제 다운로드 예외·인증 정보는 응답에 포함하지 않는다. 설치 완료 후 서버 재시작은 필요 없다. 서버 시작 자체는 캐시에서만 모델을 읽는다.

## AI 모델·프롬프트 관리

모두 기존 관리자 인증과 CSRF 정책을 적용한다. JSON 본문 한도는 64 KiB다.

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET / PATCH | `/llm/settings` | 공개 설정 / `expected_version`과 변경 필드 저장. 키는 write-only |
| GET / POST | `/llm/models`, `/llm/models/refresh` | 연결별 캐시 / 프록시 `/v1/models` 갱신 |
| POST | `/llm/check` | `{model?}`; 합성 실제 호출과 JSON 응답 진단 |
| GET | `/llm/codex/status` | 로컬 서비스·Codex 계정 수·로그인 상태 |
| POST | `/llm/codex/use` | `{expected_version}`; 로컬 서비스 연결과 키 적용 |
| POST | `/llm/codex/login` | 공식 Codex OAuth URL 생성/대기 세션 재사용 |
| POST | `/llm/codex/callback` | `{redirect_url}`; 현재 state와 localhost callback만 수락 |
| GET / POST | `/prompts` | 최신 200개 버전 목록 / 새 불변 버전 저장 |
| GET | `/prompts/active`, `/prompts/{id}` | 활성 버전 / 특정 버전 본문 |
| POST | `/prompts/{id}/activate`, `/prompts/{id}/restore` | `{expected_active_id}`; 활성 변경 / 과거 내용으로 새 버전 생성 후 활성화 |
| POST | `/prompts/preview`, `/prompts/test` | `{content?,case?,model?}`; 전송 입력 미리보기 / 합성 예시 호출 |

설정 필드: `base_url`, `api_key`, `clear_api_key`, `default_model`, `enabled`, `max_output_tokens`(256–16384), `timeout_seconds`(10–180), `input_chars`(4000–64000), `temperature`(null 또는 0–2), `reasoning_effort`(null/none/minimal/low/medium/high/xhigh). 빈 키는 기존 키 유지이며 삭제는 clear_api_key다. 주소를 바꾸며 새 키를 제공하지 않으면 기존 키가 지워진다. URL/기본 모델 변경은 워크스페이스 전송 승인을 초기화한다. JSON 오류에 키/입력 본문을 반사하지 않는다.

프롬프트 저장: `{name,content,note?,activate?,expected_active_id}`. content는 20–12000자. case는 supported/missing/conflict/injection이다. 합성 테스트는 관리자의 명시적 테스트 요청이므로 워크스페이스 동의가 필요 없으며 실제 문서를 읽지 않는다. 문서 질문은 기존의 전역·워크스페이스 승인 모두 필요하다.

실제 답변의 `llm` 필드에는 model, settings_version, prompt_id, prompt_version, prompt_hash를 보관한다. 응답 시작 시 설정/프롬프트를 고정하고 이후 변경은 다음 요청에 적용한다. 저장 경쟁 시 SETTINGS_CHANGED/PROMPT_CHANGED (409)를 반환한다. 모델 진단 결과는 연결 키·모델·옵션 조합별로 보관한다. 단순 모델 목록 포함 여부로 호출 성공을 판정하지 않는다.


## 외부 기기 폴더 업로드

| 메서드 | 경로 | 내용 |
|---|---|---|
| GET | `/uploads/limits` | 서버의 형식·개수·크기·만료 한도 |
| POST | `/uploads` | `{name,folder_name,description?,files:[{path,size}]}` → 업로드 세션(201), 파일별 서버 ID |
| GET | `/uploads/{id}` | 수신 상태. 만료 410, 정리 완료 404 |
| PUT | `/uploads/{id}/files/{file_id}` | 원시 파일 본문, Content-Type application/octet-stream; 수신 완료 후 같은 ID 재시도 가능 |
| POST | `/uploads/{id}/commit` | 모든 파일 검증 후 새 워크스페이스와 색인 작업 생성. `{workspace,job,index_error}`; 중복 완료는 같은 공간/작업 반환 |
| DELETE | `/uploads/{id}` | 미완료 전송 취소. 완료한 자료는 워크스페이스 삭제 API 사용 |

업로드 manifest만 JSON 본문 최대 8 MiB, 파일 PUT은 설정된 파일 크기까지 허용한다. 다른 JSON 요청은 64 KiB다. 모든 경로는 선택 폴더 내부의 상대 경로이며 최상위 폴더 이름은 folder_name에 별도로 보낸다. 내부 `__uploads__` 루트는 서버 폴더 등록·탐색 API로 사용할 수 없다. source.kind는 upload/server, 업로드 source.label은 선택 폴더 이름이다. 업로드 공간의 삭제 응답은 source_preserved=false이며 원래 기기의 파일에는 접근하지 않는다.
