# Tailscale에서 회의봇 접속

Tailscale Serve를 설정한 설치에서는 `https://YOUR_DEVICE.YOUR_TAILNET.ts.net/`으로 접속합니다. `YOUR_DEVICE`, `YOUR_TAILNET`, `YOUR_TAILSCALE_IP`는 설치한 서버의 실제 값으로 바꿉니다. 이 저장소가 제공하는 공용 접속 주소는 없습니다. 파일 전사, 실시간 전사, 자료 검색, 설정 및 관리가 같은 주소에서 동작합니다. 설정 방법은 [HF 준비와 Tailscale 접속](hf-and-tailscale.md)을 참고하세요.

- 회의봇: `https://YOUR_DEVICE.YOUR_TAILNET.ts.net/`
- 설정 및 관리: `https://YOUR_DEVICE.YOUR_TAILNET.ts.net/settings`
- 자료 검색: `https://YOUR_DEVICE.YOUR_TAILNET.ts.net/rag`

다른 기기도 같은 Tailscale 네트워크에 로그인한 상태에서 접속합니다. 브라우저에 표시되는 접속 키는 회의봇 최초 설치의 관리자 키입니다. 서버의 `127.0.0.1` 주소는 다른 기기에서 사용할 수 없습니다.

설정 및 관리 → 설치 및 업데이트의 **다른 기기에서 접속**에서 주소를 복사할 수 있습니다. **내 기기 접속 링크 복사**는 현재 로그인한 접속 키를 포함하므로 본인 기기에서만 사용합니다. 키는 URL fragment로 전달되며 앱이 읽은 후 주소 표시줄에서 제거합니다. 복사 성공 여부만 화면에 알리고 키 자체는 표시하지 않습니다.

## 연결 구조

```text
같은 Tailscale 네트워크의 브라우저
  → https://YOUR_DEVICE.YOUR_TAILNET.ts.net:443
  → Tailscale Serve
  → 127.0.0.1:8765 (통합 웹 · STT · 설정 API)
      → /api/rag 프록시 → 127.0.0.1:8766 (RAG)
```

IP 리스너와 리다이렉트를 설정하면 `http://YOUR_TAILSCALE_IP:8765/settings` 같은 IP 진입은 경로를 유지한 채 HTTPS로 이동합니다. 이전 RAG의 8443/8766 경로는 해당 리스너를 별도로 설정한 설치에서만 사용할 수 있습니다.

`--bg`로 등록한 Serve는 백그라운드 설정으로 유지됩니다. [Tailscale Serve](https://tailscale.com/docs/reference/tailscale-cli/serve)는 tailnet 내부에서 로컬 웹 서버로 연결합니다. 이 구성에는 Funnel이 필요하지 않습니다.

## 동작 확인

`node scripts/tailnet_ui_smoke.mjs`는 설치된 Tailscale의 실제 DNS 이름을 읽어 HTTPS 브라우저 검사를 실행합니다. 기본 Mac 앱 경로 외에는 `TAILSCALE_BIN`, Chrome 경로는 `CHROME_PATH`, 별도 설치의 키 위치는 `MEETINGBOT_TOKEN_FILE`로 지정할 수 있습니다. 설치된 Node와 frontend 의존성이 필요합니다.

검사 내용:

- HTTPS 인증서 검증, 통합 포트의 Serve 대상과 Funnel 비활성 확인.
- 로그인 전 API 거절, 로그인 후 관리 화면 5개와 전사·자료 화면 접근.
- 원격 브라우저의 API 요청이 자신의 localhost를 호출하지 않는지 확인.
- 마이크 기능에 필요한 보안 컨텍스트 확인. 실제 마이크 권한을 요청하거나 녹음하지 않습니다.
- RAG 세션과 CSRF 검증. 빈 요청으로 403/422 응답을 확인하며 저장된 설정은 바꾸지 않습니다.
- IP 진입의 HTTPS 전환과 경로 유지.

결과는 `.runtime/tailnet-qa/results.json`에 저장됩니다. 접속 키·쿠키·CSRF 값은 결과에 포함하지 않습니다.

개발 당시 이 검사는 서버 Mac에서 Tailscale Serve의 실제 HTTPS 경로를 통과했습니다. 이는 과거 개발 환경의 결과이며 새 설치의 검증 결과가 아닙니다. 별도 외부 기기를 직접 조작하지 않았으므로 해당 기기의 로그인, ACL, 방화벽 및 네트워크 도달성까지 확인한 것은 아닙니다. 서버 Mac과 Tailscale, 회의봇 서비스가 실행 중이어야 하며 Mac이 잠자기에 들어가면 접속이 중단될 수 있습니다.
