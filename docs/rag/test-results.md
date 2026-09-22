# 검증 결과

검증일: 2026-09-09 (서버 macOS 로컬 시각). 장치: Darwin arm64, MacBookAir10,1, 물리 메모리 8 GiB. 실제 임베딩은 MPS에서 실행했다. 이 수치는 환경 기록이며 최소 메모리 요구량 보장이 아니다.

| 검증 | 결과 | 구분 |
|---|---|---|
| RAG API·저장소·실패·보안 테스트 | **25 passed** | 임베딩만 모의 모델. 실제 FastAPI/SQLite/Qdrant/파서 사용 |
| 프론트 단위 테스트 | **15 passed, 4 files** | 기존 STT 12개 + RAG 3개 |
| 기존 STT 회귀 테스트 | **55 passed** | 기존 STT 테스트 그대로 실행 |
| Python lint / React·TypeScript 운영 빌드 | **통과** | ruff / tsc + Vite production |
| 실제 모델 + Tailscale HTTPS API 통합 | **최초 37 / 최종 재검증 35 checks passed**, 한국어 평가 **5/5** | 실제 multilingual-e5-small/MPS/디스크 저장소/인증 HTTPS |
| 실제 Chrome E2E | **9 checks passed**, pageerror **0** | 운영 HTTPS UI, 네트워크/API mock 없음(늦은 응답 검증에만 응답 지연 주입) |
| 실제 프로세스 강제 종료 복구 | **3 checks passed** | 진행 중 RAG SIGKILL, LaunchAgent 자동 복구, 기존 READY 검색 유지 |
| 백업 복구 CLI | **통과** | 실제 tar.gz를 임시 빈 경로에 복구, 덮어쓰기/경로 탈출 거절 |
| 별도 외부 네트워크의 원격 기기 | **미검증** | 서버에서 tailnet HTTPS 경유 검증과 구분 |
| 실제 CLIProxyAPI LLM | **통과** | Codex 계정 연결, gpt-5.6-terra 실제 호출·JSON, 프롬프트 4종 및 샘플 RAG 2종 |

최종 재검증은 이미 만들어진 샘플 공간 2개를 재사용해 생성 체크 2개를 생략했다. 최종 실제 모델 카운터는 재색인 전후 모두 20으로 유지됐고, A 문서 4개를 재사용했다.

## 확인한 동작

- 미인증 루트/문서/근거 접근 거절, Host/Origin/CSRF, Secure HttpOnly 쿠키, 입력 검증에서 비밀값 반사 방지.
- 상위/절대/인코딩 경로 탈출, 심볼릭 링크/하드 링크, 제외 정책, root 재매핑과 권한 회수 차단.
- A/B의 같은 `logs.md`에서 90일/30일을 구분하고 원문 줄과 표 셀을 조회.
- MD/TXT 문서/줄 위치, CSV/TSV 앞자리 0/빈 문자열/숫자 문자열, XLSX 숫자/날짜/비율/수식·캐시없음/숨김 시트·행 보존 정책.
- 변경 없는 4개 문서 재색인에서 **새 임베딩 0개**, 기존 벡터·추출 결과 재사용. 변경/삭제 파일과 과거 스냅샷 유지.
- PARTIAL·취소·폴더 접근 불가·강제 종료에서 기존 READY 포인터 보존. 같은 공간 구축 중복/idempotency 처리.
- 워크스페이스 삭제 중 늦게 끝난 작업이 데이터를 다시 만들지 않음. 원본과 다른 공간 보존.
- 전송 승인 없으면 LLM 0회. 프록시 실패/잘못된 인용/철회는 모의 provider로 확인. 로컬 검색은 유지.
- 보존/활성 버전 삭제 차단, 과거 버전 명시 삭제 후 활성 검색 유지.
- 브라우저에서 서버 폴더 선택, 수집 미리보기, 생성·색인, 탭 종료 후 복원, 검색·원문, 공간 변경 후 결과 초기화, 늦은 이전 공간 응답 폐기.
- 390px 모바일 가로 넘침 없음. 실제 브라우저 API 주소가 공개 HTTPS origin에만 연결됨.

실측 단계 시간과 근거는 [실제 API 결과](real-integration-results.json), [브라우저 결과](ui-test-results.json), [강제 종료 복구 결과](recovery-test-results.json)에 기록했다. 최초 실측의 A 4문서/7청크는 약 7.1초, B 3문서/6청크는 약 1.0초였다. 모델 초기 준비 이후의 작은 합성 자료 수치이며 다른 파일/하드웨어/정확도에 일반화하지 않는다. 재실행 결과 파일의 수치는 캐시·재사용 여부에 따라 달라진다.

## 재현 명령

프로젝트 루트에서:

```sh
uv sync --project rag --frozen
uv run --project rag pytest rag/tests -q
uv run --project rag ruff check rag/meetingbot_rag
npm --prefix frontend test
npm --prefix frontend run build
backend/.venv/bin/python -m pytest backend/tests -q
# 준비된 운영 RAG + 합성 ~/MeetingDocs/sample-project-a,b 필요
rag/.venv/bin/python scripts/rag_smoke.py
node scripts/rag_ui_smoke.mjs
# 이 테스트는 RAG 프로세스를 실제 종료하고 launchd 복구를 확인함
rag/.venv/bin/python scripts/rag_recovery_smoke.py
```

브라우저 테스트는 로컬 Chrome을 사용한다. 다른 경로는 CHROME_PATH 환경 변수로 지정한다. 검증용 공간은 테스트 종료 시 삭제하며 사용자 원본은 변경하지 않는다. 재시작 테스트는 생성한 임시 합성 폴더만 삭제한다. 실제 외부 전송/공개 네트워크 reachability/새 서버 설치를 실행한 것처럼 보고하지 않는다.

pytest 경고: Starlette/anyio의 deprecated alias 및 기존 STT TestClient 경고가 있었지만 테스트 실패는 없었다. 모의 임베딩의 통과를 실제 한국어 검색 품질로 취급하지 않는다.

통합 재검증 중 UI 색인과 API 증분 테스트를 동시에 실행하면 모델의 전역 계산 카운터가 다른 공간의 색인으로 증가하여 카운터 assertion이 실패했다. 두 테스트를 직렬로 다시 실행해 통과를 확인했다. 각 워크스페이스의 재사용 결과는 정상이며, 재현 시 위 통합 테스트 명령은 순서대로 실행한다.


## CLIProxyAPI · 모델/프롬프트 관리 (2026-09-09)

RAG pytest **49개 통과**, frontend Vitest **15개 통과**, TypeScript/Vite 빌드와 RAG lint 통과. 새 테스트는 설정 경쟁/키 비노출/연결별 모델 캐시/모델 변경 동의 철회, 불변 프롬프트 버전·복원·충돌, v1→v2 DB 보존, 실제 LangChain/OpenAI SDK의 합성 HTTP 요청/응답, OAuth state·callback 검증, 계정 모델이 없는 상태의 명시적 진단을 포함한다.

실제 HTTPS 배포에서 설정 저장과 서버 재시작 후 복원, E5 한글 검색(A 90일/B 30일 격리), 인증 없는 관리 API 차단, IP→HTTPS 리디렉션, STT health 200을 확인했다. 브라우저에서는 세션/CSRF 저장, 프롬프트 입력 미리보기, 데스크톱과 390px 모바일 레이아웃·가로 넘침 없음·콘솔 오류 없음까지 확인했다. 자동 검증 결과는 [llm-test-results.json](llm-test-results.json)에 남겼다.

한 번의 테스트 실행은 Vite가 dist/assets를 교체하는 순간과 겹쳐 static mount fixture 초기화가 실패했다. 빌드를 완료한 뒤 순차 재실행하여 49개 모두 통과했다. 운영 배포는 서비스를 중지한 상태에서 완성된 빌드를 복사한다. 재시작 스크립트는 포트 종료와 launchd 등록 해제를 모두 기다리도록 수정해 비동기 bootout/백업 경쟁도 해결했다.

**후속 실제 계정 검증 완료(2026-09-09):** Codex 계정 연결, gpt-5.6-terra 실제 호출·JSON 응답을 확인했다. 프롬프트 v2에서 근거 있음/부족/충돌/악성 지시 4종이 통과했고 실제 E5 검색을 거친 샘플 A 90일/B 30일 RAG 답변도 확인했다. 근거 부족 분류를 보완한 v2를 관리 이력에 저장했다. [live-llm-results.json](live-llm-results.json). 일반 자료의 정확도·계정 한도는 별도 검증 범위다.

## 외부 폴더 업로드 추가 검증 (2026-09-09)

- 전체 RAG 백엔드 77개, 프런트엔드 20개 통과. TypeScript/Vite 배포 빌드 통과.
- 업로드 경로 탈출·숨김/보호 파일·유니코드/대소문자 충돌·파일/폴더 개수·크기·보관 한도 검증. 실제 스트림 크기 불일치·중단·미완료 게시·위조 Origin/CSRF 차단.
- 파일 수신 상태 재시작 복구, 취소/만료 정리, 게시 중 DB 실패 후 재시도, 게시 멱등성, 대기열 초과 시 사본 보관 및 재색인 확인.
- 실제 Tailscale HTTPS + 쿠키/CSRF로 84,000바이트 전송/취소, 한글 하위 경로의 MD/CSV/XLSX 3개 자동 색인 READY, 실제 E5 검색 75일 및 원문 snapshot 확인.
- RAG 재시작 후 업로드 원문·색인·검색이 유지됨. 기존 샘플 A 90일/B 30일 검색과 공간 분리 유지. 테스트용 공간 정리 후 서버 사본 삭제 확인, STT health 200.
- 업로드 테스트의 첫 합성 파일은 빈 줄 70,000개가 기존 청킹 시간 제한에 걸려 PARTIAL이 됐다. 정상 게시 실패 상태와 기존 자료 보존을 확인했으며, 전송 한도 검증과 정상 문서 색인 검증을 분리해 위 결과를 얻었다. 파서 시간 제한을 변경하지 않았다.
- Mac이 잠겨 있어 이번 업로드 화면의 실제 브라우저 시각 검증은 수행하지 못했다. 다른 물리 기기/외부 네트워크에서의 업로드도 별도 확인이 필요하다. 이전 화면 QA와 구분한다.

세부 결과: [folder-upload-test-results.json](folder-upload-test-results.json). 재실행: `rag/.venv/bin/python scripts/eval_uploads.py --stage create`, RAG 재시작 후 `--stage verify`. 생성 단계는 합성 검증 공간을 만들고 검증 단계에서 정리한다.
