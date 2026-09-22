# 회의봇 RAG 구조

RAG는 기존 STT와 별도 Python 프로젝트(`rag/`) 및 별도 단일 프로세스로 실행된다. React 빌드에는 `/rag`에서만 로드되는 화면을 추가했다. STT의 오디오 처리, 모델, API, 서비스 정의는 변경하지 않았다. 8765는 STT, 8766은 RAG의 loopback 포트다. API는 `/api/rag`, 화면은 `/rag`이며 브라우저 API는 모두 상대 경로다.

```
브라우저 → Tailscale Serve HTTPS :8443 → FastAPI 127.0.0.1:8766
         → 인증·Origin·CSRF → Workspace / SourceBrowser
         → SQLite 영속 작업 → 단일 ingestion 작업자
         → descriptor 기반 읽기 → 파서 subprocess → 청킹 → 로컬 E5
         → Qdrant 전용 소유 스레드 + 버전별 SQLite FTS5
         → 스냅샷·청크·벡터 검증 → active_revision_id 원자 전환
질문 → 고정된 workspace/revision → 벡터 + FTS → RRF → 근거
     → 선택적으로 전역+공간 승인 확인 → CLIProxyAPI → 인용 ID 검증
```

- `SourceBrowserService`: 로컬 YAML allowlist, 디렉터리 descriptor 탐색, no-follow 파일 열기, 범위와 접근 재검증.
- `WorkspaceService`: Workspace / KnowledgeBase / SourceFolder 분리, 정책 회수, 이름·설명·전송 동의.
- `IngestionService`: 영속 작업, heartbeat, 직렬 구축, 스캔, 파싱, 내용 해시 기반 재사용, 취소, 재시작 복구.
- `RevisionService`: READY 버전 확인·활성화, 보존 설정과 명시적 버전 삭제.
- `RetrievalService`: 현재 활성 버전을 한 번 확정하거나 명시 버전 사용, 벡터·FTS 범위를 처음부터 해당 버전으로 제한. 검색 동시 요청 최대 2개.
- `EvidenceService`: 검색 당시 보관 원문을 검증된 ID 조합으로 반환.
- `AnswerService` / `LLMProviderFactory`: 일반 Python 2단계 검색·생성, 도구 없음, 전송 동의·예산·인용 검증. STT 의존 없음.

저장 구조:

```
RAG_DATA_DIR/
  registry.sqlite               # SQLite WAL, schema_version, 작업/공간/질문 메타데이터
  models/                       # 고정 모델 revision, 공간 간 가중치만 공유
  workspaces/{workspace_id}/
    snapshots/{document_version_id}.bin
    vectors/                    # Qdrant 단일 클라이언트; 컬렉션은 revision_id
    revisions/{revision_id}/
      manifest.json
      keyword.sqlite            # 해당 버전의 근거 JSON, FTS5
```

`registry.sqlite`는 단일 관리자 MVP용 공유 DB다. 문서·문서 버전·질문·작업 쿼리에 workspace_id를 항상 적용한다. 원문 스냅샷과 벡터는 공간별 디렉터리로 분리한다. 한 경로의 Qdrant 클라이언트는 전용 실행기에서만 생성·호출·종료한다. `flock`으로 두 번째 API 프로세스도 막는다. API의 동기 핸들러는 ASGI worker thread에서 수행되어 이벤트 루프에서 임베딩·벡터 검색을 직접 실행하지 않는다.

파일별 처리 실패는 PARTIAL이며 자동 활성화하지 않는다. 파서 subprocess는 시간 제한 시 종료된다. 구축 도중 원본 폴더를 읽을 수 없으면 기존 버전은 그대로 유지되며 접근 회수 시 검색도 차단된다. 재시작 시 QUEUED/RUNNING 작업은 `SERVER_RESTARTED` FAILED로 전환하고 사용자가 새 작업으로 재시도한다. 자동 무한 재시도는 하지 않는다. 파일 읽기는 변경 감지 시 최대 2회 시도한다.

전체 폴더가 같은 순간에 읽혔다는 보장은 없다. manifest는 실제 읽은 내용 해시/문서 버전을 기록한다. 벡터 계산 재사용과 새 컬렉션의 디스크 쓰기는 구분한다. 처리 설정 fingerprint에는 파서·청킹·표 해석·모델 revision·E5 prefix·정규화가 포함된다. 모델이 변경된 과거 버전에 새 모델 질의를 섞지 않는다.

외부 업로드는 `UploadService`의 manifest/파일 스트림/게시 단계로 처리한다. upload-staging에서 수신을 완료한 뒤 uploaded로 트리를 게시하고, 내부 소스 루트로 기존 색인 경로를 재사용한다. 외부 폴더 업로드 전용 API만 이 내부 루트에 자료를 생성할 수 있다. [상세 계약](folder-upload.md).
