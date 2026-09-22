# Tailscale 원격 접속

새 설치는 [통합 원격 접속 안내](../tailnet-access.md)를 따릅니다. 전사·자료·관리가 같은 주소에 있습니다. 아래 내용은 RAG를 별도 8443/8766 포트로 운영할 때의 안내입니다. `YOUR_DEVICE`, `YOUR_TAILNET`, `YOUR_TAILSCALE_IP`는 설치한 서버의 실제 값으로 바꿉니다.

설정 후 사용할 주소:

- Tailscale IP 진입: `http://YOUR_TAILSCALE_IP:8766/rag`
- RAG HTTPS 화면: `https://YOUR_DEVICE.YOUR_TAILNET.ts.net:8443/rag`

같은 tailnet에 로그인한 다른 기기에서 IP 진입을 열면 MagicDNS HTTPS 이름으로 이동한다. 기존 회의봇 관리자 접속 키로 로그인한다. 키 포함 링크는 서버에서 `python3 scripts/rag.py access-link`로 확인한다. IP 자체의 인증서를 새로 만드는 방식이 아니다.

```
http://YOUR_TAILSCALE_IP:8766/rag → 307 HTTPS 이동
https://YOUR_DEVICE.YOUR_TAILNET.ts.net:8443/rag
  → Tailscale Serve TLS 종료 → 127.0.0.1:8766
```

서버 웹과 API는 같은 origin이다. 문서 루트/키/Qdrant/CLIProxyAPI 포트는 Serve에 등록하지 않는다. 이 연결은 인터넷을 통과할 수 있는 사설 tailnet 접속이며 누구나 방문 가능한 익명 인터넷 사이트가 아니다. 이 구성에는 Funnel이 필요하지 않다.

## 설정·중지

```sh
python3 scripts/rag.py tailscale
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status
# RAG 원격 연결만 해제
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --https=8443 off
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --tcp=8766 off
```

`tailscale` 명령은 해당 포트의 기존 소유자를 확인하고 동일한 RAG 설정일 때만 재사용한다. 다른 Serve 라우트를 reset하지 않는다. 별도 Caddy 배포는 `config/Caddyfile.rag.example`로 제공한다. 운영자 도메인·DNS·HTTPS가 필요하고 `.env.rag`의 RAG_PUBLIC_ORIGIN/ALLOWED_HOSTS/ORIGINS를 정확히 맞춘다. backend는 loopback, uvicorn은 trusted proxy loopback만 신뢰한다.

## 외부 기기 확인 절차

1. 서버 Mac과 원격 기기의 Tailscale 연결, 서버의 전원/잠자기 상태를 확인한다.
2. 원격 기기를 별도 네트워크(예: 휴대전화 데이터)에 연결하고 IP 진입 주소를 연다.
3. HTTPS 이동, 인증서 경고 없음, 로그인 전 데이터 접근 거절, 로그인 후 같은 샘플 A/B 목록을 확인한다.
4. 웹에서 허용 루트 안의 폴더를 선택해 새 워크스페이스를 만든다.
5. 자료 준비를 시작한 후 탭을 닫았다가 다시 접속한다. 준비 상태가 복원되는지 확인한다.
6. A의 로그 보관 근거 90일, B의 30일과 원문 줄/셀을 확인한다.
7. 개발자 도구의 API 주소가 현재 HTTPS origin인지 확인한다. 브라우저 자신의 127.0.0.1을 호출하면 안 된다.

과거 개발 환경의 서버 Mac에서 실제 Tailscale IP→307 및 Serve HTTPS 경로를 통과한 API/브라우저 테스트를 수행했다. 이는 새 설치의 검증 결과가 아니다. 별도 LAN 기기 또는 실제 외부 네트워크의 기기는 검증하지 않았으므로 해당 기기의 ACL·방화벽·도달 가능성은 설치 후 별도로 확인한다.
