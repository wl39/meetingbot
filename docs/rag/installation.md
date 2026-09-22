# macOS 설치·운영

새 설치의 기본 절차는 [통합 설치 안내](../installation.md)를 따른다. 이 문서는 macOS에서 RAG를 별도 LaunchAgent로 운영할 때의 상세 안내다. `YOUR_SOURCE_DIR`는 저장소를 내려받은 실제 폴더로 바꾼다.

## 기본 저장 위치

- 소스: `/YOUR_SOURCE_DIR/meetingbot`
- 실행본: `~/Library/Application Support/MeetingbotRAG`
- 데이터: `~/Library/Application Support/MeetingbotRAG/data`
- 원본 허용 루트: `~/MeetingDocs`
- 서비스: `com.meetingbot.rag` (사용자 LaunchAgent, 로그인 시 자동 실행)
- 로그: `~/Library/Logs/MeetingbotRAG`

STT의 실행본·데이터·LaunchAgent는 별도다. RAG는 STT 라이브러리를 import하지 않는다.

## 새 서버 설치

macOS arm64와 Python 3.11–3.12, uv, Node.js/npm이 필요하다. 설치 스크립트는 다른 OS를 지원한다고 가정하지 않으며 uv/npm 및 웹 빌드를 점검한다.

```sh
cd /YOUR_SOURCE_DIR/meetingbot
python3 scripts/rag.py init
# config/source-roots.yaml 에 실제 읽기 가능한 자료 폴더 설정
# 필요할 때 .env.rag 수정; 비밀번호/키를 저장소에 넣지 않기
python3 scripts/rag.py install
uv run --project rag python scripts/rag.py download-model
python3 scripts/rag.py restart
python3 scripts/rag.py access-link
```

`init`은 이미 있는 설정/키/문서를 덮어쓰지 않는다. 신규 키는 로컬 CLI에서만 생성한다. 기존 STT 관리자 키를 공유하려면 `.env.rag`의 `RAG_AUTH_TOKEN_FILE`을 해당 키 파일로 설정한다. `access-link`의 fragment 토큰은 브라우저에서 로그인 후 즉시 주소에서 지워지며 서버 URL 로그로 전송되지 않는다. 출력은 본인이 사용하는 장치에만 전달한다.

서버 시작은 캐시에서만 모델을 읽는다. 웹 관리 화면에서 임베딩 준비를 요청하면 고정 revision을 내려받고 재시작 없이 바로 사용할 수 있다. `GET /api/rag/embedding`과 `POST /api/rag/embedding/install`로 다운로드·실패·재시도 상태를 확인한다. 기존 `download-model` CLI도 유지한다. LLM 키 없이도 로컬 색인/검색이 가능하다.

## 시작·중지·업데이트

```sh
python3 scripts/rag.py status
python3 scripts/rag.py stop
python3 scripts/rag.py start
# 소스 수정 후 업데이트
uv sync --project rag --frozen
npm --prefix frontend ci --cache "$HOME/Library/Application Support/MeetingbotRAG/npm-cache"
npm --prefix frontend run build
python3 scripts/rag.py restart
```

`start/restart`는 실행 중인 RAG만 중지하고 기존 DB가 있으면 먼저 백업한 다음 실행본과 웹 빌드를 갱신한다. `uv.lock`의 버전을 `--frozen`으로 적용한다. 현재 스키마는 `schema_version=4`다. 기존 v1–v3 데이터는 `002_llm_management.sql`, `003_folder_uploads.sql`, `004_rag_settings.sql` 마이그레이션 트랜잭션으로 보존하며 확장한다. 모델 설정, 프롬프트 버전, 웹에서 저장한 청킹·검색 설정은 DB에 저장되어 배포·재시작 후에도 유지된다. 알 수 없는 스키마 버전은 거절한다. 초기 소스 정책의 루트 식별자 보강은 `Core`에서 1회 수행한다. 모델 또는 파서 설정이 달라지면 fingerprint에 따라 새 자료 버전을 구축해야 한다.

LaunchAgent는 로그인한 사용자 권한으로 실행된다. Documents/Desktop/외장 드라이브 등 macOS 보호 위치는 서비스 프로세스에 파일 접근 권한이 추가로 필요할 수 있다. 웹에서 보이는 허용 폴더는 반드시 해당 계정이 실제로 읽을 수 있어야 한다. 서비스 실행본은 Documents 밖의 앱 데이터 폴더에 둔다. 기기의 잠자기·방화벽·tailnet ACL은 운영 환경에 맞게 확인한다.

원본 허용 루트를 수정할 때 소스의 `config/source-roots.yaml`을 수정하고 `restart`로 반영한다. 운영 중 즉시 회수하려면 실행본의 `config/source-roots.yaml`도 함께 수정한다. 이 파일은 매 요청 다시 읽는다. 기존 root_id의 실제 경로를 바꾸면 기존 공간 접근은 거절된다. 새 공간으로 다시 연결한다.

## 백업·복구·제거

```sh
python3 scripts/rag.py stop
python3 scripts/rag.py backup
# .env.rag 의 RAG_DATA_DIR를 새 빈 디렉터리로 설정한 뒤
python3 scripts/rag.py restore --archive /path/to/backup.tar.gz
python3 scripts/rag.py start
```

백업은 서비스 중지와 데이터 소유 잠금을 확인한다. DB/WAL·스냅샷·벡터·자료 버전·질문 기록을 함께 보관한다. 모델 가중치와 관리자 키는 제외하므로 별도 보관하거나 재다운로드한다. 백업 DB에는 웹에서 저장한 CLIProxyAPI 연결 키와 프롬프트도 포함된다. 백업을 비밀 자료로 관리해야 한다. `.env.rag`, 허용 루트 설정 및 별도 `MeetingbotCLIProxy/auth`의 Codex 인증 자료는 백업에 포함되지 않으므로 따로 보호하거나 재로그인한다. 복구는 빈 디렉터리에만 허용하고 절대 경로·탈출·링크 아카이브를 거절한다. 원본 폴더의 root_id/경로가 같고 접근 가능해야 과거 자료도 조회된다.

```sh
python3 scripts/rag.py uninstall
```

제거는 RAG LaunchAgent만 내린다. 사용자 데이터, 모델, 키, 원본, STT는 보존한다. 앱 자료 삭제는 인증된 웹의 워크스페이스 삭제 또는 버전 삭제 API로 명시적으로 수행한다. 저장 매체 완전 삭제가 필요하면 백업을 포함한 별도 저장매체 정책을 사용한다.

Tailscale 연결을 끄려면 RAG가 만든 8443/8766 리스너만 해제한다. 기존 STT 443/8765는 그대로 둔다. 자세한 명령은 `remote-access.md`를 참조한다.

## Codex / CLIProxyAPI

설치·로그인·모델·프롬프트 운영 절차는 [AI 설정 가이드](llm-management.md)를 따른다.
