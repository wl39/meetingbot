# 소스 구조와 모듈 경계

화면과 API의 기존 동작을 유지하면서, 큰 파일을 역할별로 분리했습니다. 단순히 줄 수를 줄이기보다 변경할 기능의 코드와 상태를 한곳에서 찾을 수 있도록 구성했습니다.

## 프론트엔드

| 위치 | 역할 |
| --- | --- |
| `src/workspace/` | 공통 탐색·로그인 키·전사 중 화면 이동과 방문 화면 유지 |
| `src/components/ui/` | 기능에 의존하지 않는 공용 UI: 상태/오류 알림, 닫기 버튼, 섹션 제목·설명·보조 동작 |
| `src/features/management/ManagementPage.tsx` | 설정 페이지 구성과 탭 선택 |
| `src/features/management/hooks/` | 서버 상태와 RAG 설정 조회·저장·폴링·작업 상태 |
| `src/features/management/*Section.tsx` | 관리 홈·음성 인식·자료 검색·업데이트 섹션 |
| `src/features/management/components/` | 청킹 폼, 재색인 목록, 임베딩 카드, 설치 기록, 원격 접속, 화면 설정 |
| `src/features/rag/library/` | 로그인과 라이브러리 목록 상태, 라이브러리 화면 |
| `src/features/rag/sources/` | 자료 폴더 탐색·워크스페이스 만들기 |
| `src/features/rag/workspace/` | 선택한 자료의 상태, 검색·자료·설정 탭, 근거 원문 패널 |
| `src/features/rag/llm/` | AI 설정 상태·계정 연결·모델 옵션·연결 확인·프롬프트 편집/미리보기/버전 기록 |
| `src/features/stt/` | 파일 전사·실시간 입력·대본·로컬 재생과 파형·전사 옵션 |
| `src/features/meeting/` | 실시간 회의 도우미와 근거 큐 |

공용 UI는 React props만 받고 기능 API나 워크스페이스 상태를 직접 참조하지 않습니다. 외형이 조금씩 다른 화면은 `className`, `icon`, `children`으로 기존 디자인을 유지합니다. 청크·모델·화자처럼 도메인 의미가 있는 컴포넌트는 해당 기능 안에 둡니다.

페이지는 조립을 담당하고, 조회·저장·폴링은 훅이 관리합니다. 화면 탭을 이동해도 유지되어야 하는 값은 부모 훅에 둡니다. 기존 API 모듈, 로그인/CSRF 흐름, 컴포넌트 공개 진입점은 유지했습니다.

주요 페이지 크기는 관리 1,285→153줄, RAG 1,493→223줄, AI 설정 964→120줄입니다. 옮긴 로직은 해당 기능의 훅과 세부 컴포넌트에서 찾을 수 있습니다.

## 백엔드

STT `app/main.py`는 설정과 라우터를 조립하는 Uvicorn 팩토리로 유지합니다.

- `app/http.py`: 요청 크기 제한, Host/Origin/접속 키 검증, CORS, 정적 웹 경로.
- `app/lifecycle.py`: 저장소·워커·런타임 관리자 생성과 정상 종료.
- `app/modules/stt/routes/`: 세션, 파일 업로드, 실시간 WebSocket, 공통 의존성/준비 검사.
- `app/modules/stt/`: 기존 전사 처리 서비스·저장소·엔진.
- `app/modules/system/`: 설치 카탈로그·백그라운드 설치·모델 전환.
- `app/modules/meeting/`: 회의 도우미 연결과 같은 origin의 RAG 프록시.

RAG `meetingbot_rag/app.py`도 앱 조립과 웹 진입점만 담당합니다.

- `api/`: 인증, 소스, 워크스페이스, 업로드, 관리 API 라우터.
- `schemas.py`: API 입력 구조와 검증.
- `http.py`: 인증·세션·CSRF·요청 제한과 오류 응답.
- `lifecycle.py`: 모델 준비·프로세스 잠금·업로드 정리·종료.
- `services/core.py`: 도메인 서비스 조립과 공유 자원 수명.
- `services/workspaces.py`: 워크스페이스와 작업 표현.
- `services/revisions.py`: 자료 버전과 활성 버전 전환.
- `services/ingestion.py`: 문서 색인 파이프라인.
- `services/retrieval.py`: 근거 조회와 검색.

기존 `create_app` 실행 경로 및 `meetingbot_rag.services`의 Core·서비스 import는 유지됩니다. HTTP 계층은 요청을 검증하고 서비스를 호출하며, 모델 추론과 색인 작업을 직접 구현하지 않습니다. STT와 RAG의 가상 환경·저장소 분리도 유지합니다.

## 배포와 검증

두 Mac 서비스 배포 스크립트는 `scripts/support/deployment.py`의 코드 교체 함수를 공유합니다. 중지한 서비스의 Python 소스만 임시 위치에 복사한 뒤 교체하여 삭제된 이전 모듈이 실행본에 남지 않게 합니다. 복사 실패 시 기존 소스를 유지하고, 교체 실패 시 이전 소스로 복구합니다. 데이터·모델·가상 환경은 교체 대상에 포함하지 않습니다.

리팩터링 전 실행본과 변경한 소스의 OpenAPI를 비교하여 STT 31개, RAG 48개 경로의 요청·응답 정의 및 모든 스키마가 동일함을 확인했습니다. `/api/system` 응답에는 설정된 원격 주소만 추가하며 실제 연결 여부를 추측해 표시하지 않습니다.

검증 명령:

```sh
npm --prefix frontend test
npm --prefix frontend run build
backend/.venv/bin/python -m pytest backend/tests -q
rag/.venv/bin/python -m pytest rag/tests -q
python3 -m unittest discover -s scripts/tests -v
node scripts/management_ui_smoke.mjs
node scripts/rag_modular_ui_smoke.mjs
node scripts/tailnet_ui_smoke.mjs
```

Windows 가상 환경은 `.venv/Scripts/python.exe` 경로를 사용합니다. 브라우저 검사에서 사용하는 실제 API와 합성 API는 각 스크립트의 설명을 확인합니다. Tailscale 검사는 [원격 접속 문서](tailnet-access.md)를 참고하세요.

최종 검사에서 프론트엔드 47개, STT 123개, RAG 137개, 배포 복구 4개가 통과했습니다. 별도 브라우저 검사는 관리·RAG·전사 시나리오와 실제 Tailscale HTTPS 경로를 확인합니다.
