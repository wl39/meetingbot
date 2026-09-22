# Codex 연결과 AI 설정

미팅봇의 설정 화면에서 연결·기본 모델과 프롬프트를 관리한다. 로컬 통합 화면은 `http://127.0.0.1:8765/settings/ai`다. Tailscale은 [원격 접속 안내](../tailnet-access.md)에 따라 본인 서버 주소를 사용하고, 본인 설치의 관리자 키로 로그인한다.

## 과거 개발 환경의 검증 기록

개발 당시 CLIProxyAPI **v7.2.155**를 macOS에 설치해 검증했다. 당시 설정은 `gpt-5.6-terra`, 추론 `low`, 최대 출력 4096 토큰, 응답 제한 90초, 입력 한도 24000자였고 Temperature는 별도 지정하지 않았다. **2026-09-09 실제 Codex 계정 연결과 해당 모델 호출·JSON 응답을 확인했다.** 활성 프롬프트 v2로 근거 있음/부족/충돌/악성 지시 4개 상황과 샘플 A·B의 실제 RAG 답변을 검증했다. 미정인 값을 근거 부족으로 분류하도록 v1을 보완하고 v2 이력으로 저장했다. [당시 호출 결과](live-llm-results.json). 이는 새 설치의 연결 상태나 현재 계정에서 제공하는 모델을 보장하지 않으며, 설치 후 본인 계정의 모델 목록과 연결 테스트로 확인한다.

## macOS 설치 위치

- 실행 위치: `~/Library/Application Support/MeetingbotCLIProxy`
- 서비스: `com.meetingbot.cliproxy` (로그인 시 자동 실행)
- 주소: `http://127.0.0.1:8317/v1` (외부에 직접 노출하지 않음)
- RAG 전용 연결 키/관리 키: `credentials.json` (0600)
- 프록시 설정: `config.yaml`, OAuth 보관 위치: `auth/`
- 일반 서비스 로그: `~/Library/Logs/MeetingbotCLIProxy`

기존 Codex 앱의 설정이나 로그인 파일은 수정하지 않는다. CLIProxyAPI를 위한 OAuth 로그인을 별도로 완료한다. 인증은 OpenAI 공식 화면에서 수행하며, 인증 자격 증명은 로컬 프록시에 보관한다. [OpenAI 인증 문서](https://learn.chatgpt.com/docs/auth).

## 로그인

1. **Codex 로그인 → OpenAI 로그인 창 열기**를 선택한다.
2. 연결할 ChatGPT 계정으로 로그인하고 연결을 완료한다.
3. 이 Mac에서 로그인했다면 callback을 자동 처리한다. 다른 기기라면 localhost 오류 화면의 주소 전체를 **다른 기기에서 로그인하나요?**에 붙여넣고 연결 완료를 누른다.
4. 연결됨이 표시되면 **모델 목록 불러오기**로 계정의 목록을 확인한다. 필요하면 기본 모델을 바꾸고 저장한다.
5. **연결 테스트**에서 실제 응답·JSON 형식이 확인되는지 점검한다.
6. 자료를 보낼 워크스페이스의 설정에서 질문·근거 전송을 승인한다. 모델/주소를 바꾸면 이 승인은 초기화된다.

인증 세션이 만료되면 다시 Codex 로그인을 누른다. 키를 채팅에 붙여넣을 필요가 없다. **이 Mac의 연결 사용**은 서버에 설치된 프록시 키를 직접 적용한다. 외부 CLIProxyAPI 주소를 사용할 때는 주소와 연결 키를 입력하고 저장한다.

## 프롬프트

기본 한국어 지침은 결론 우선, 자료 밖 사실 제한, 숫자·날짜·단위 보존, 근거 부족/충돌 처리, 표 전체 집계 제한, 문서 내 악성 지시 무시를 포함한다. JSON 출력 계약과 인용 ID 검증은 서버가 추가 적용한다.

- **새 버전 저장**: 초안 보관. 현재 답변 지침은 그대로 유지된다.
- **저장하고 적용**: 새 버전을 만들어 이후 답변에 적용한다.
- **이 버전 적용**: 저장된 특정 버전을 활성화한다.
- **이 내용으로 새 버전 복원**: 이전 내용을 새 버전으로 복원해 이력을 보존한다.
- **입력 미리보기**: 실제로 전송할 프롬프트와 합성 질문/근거를 확인한다.
- **예시 답변 생성**: 근거 있음/없음/충돌/악성 지시 네 가지 합성 상황을 연결된 모델로 시험한다. 편집 중인 지침을 사용하며 저장을 요구하지 않는다.

프롬프트 버전과 내용 해시, 사용 모델은 각 답변 기록에 남는다. 지침만 바꿀 때는 재색인하지 않는다. 첫 기본 지침을 만든 뒤에는 소스 `prompts/rag_answer.md`의 변경이 웹에서 저장한 활성 버전을 덮어쓰지 않는다.

## 설치·운영 명령

```sh
python3 scripts/cliproxy.py install
python3 scripts/rag.py restart
python3 scripts/cliproxy.py status
python3 scripts/cliproxy.py login
python3 scripts/cliproxy.py stop
python3 scripts/cliproxy.py start
```

install은 고정 arm64 공식 릴리스의 SHA256을 검증한다. 기존 config/인증 자료를 보존하고 랜덤 키는 최초 설치 때만 만든다. 새 버전 업데이트는 버전/체크섬을 검토해 스크립트를 변경한 뒤 명시적으로 설치한다. 파일을 받기만 하고 임의 원격 설치 스크립트를 실행하지 않는다.

SHA256: `f90c503ce41a798c85b6f61dfe5fe8b812c1b889634f0c80d04ee376424fe305`.
[공식 릴리스](https://github.com/router-for-me/CLIProxyAPI/releases/tag/v7.2.155), [관리 API](https://help.router-for.me/management/api), [설치 버전의 Codex 모델 목록](https://github.com/router-for-me/CLIProxyAPI/blob/v7.2.155/internal/registry/models/models.json), [OpenAI 모델 목록](https://developers.openai.com/api/docs/models/all).

## 실패 시

모델 목록이 비어 있으면 Codex 로그인 상태를 확인한다. 목록에 있어도 실제 호출이 실패할 수 있으므로 연결 테스트를 별도로 수행한다. 사용 한도·인증 오류·타임아웃·모델 옵션 오류를 구분한다. 오류여도 로컬 근거 검색과 원문 조회는 유지된다. 프롬프트 검증은 형식/인용 ID 검사이며 자연어 의미의 정확성을 보장하지 않는다. 실제 계정의 응답 검증 전에는 연결 완료로 판단하지 않는다.
