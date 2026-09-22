# Hugging Face 준비와 Tailscale 접속

## HF 준비

HF는 Hugging Face입니다. 기본 설치와 Whisper 모델 준비는 [설치 안내](installation.md)를 먼저 따릅니다. 화자 분리를 사용하려면 Community-1 모델의 접근 권한과 다운로드가 추가로 필요합니다. 아래 `YOUR_SOURCE_DIR`, `YOUR_DEVICE`, `YOUR_TAILNET`, `YOUR_TAILSCALE_IP`는 본인 설치의 실제 값으로 바꿉니다.

1. [Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1)에 본인 계정으로 로그인하고 접근 조건에 동의합니다. 모델 페이지에 접근 승인 상태가 표시되어야 합니다. 조건 동의는 사용자가 직접 해야 합니다.
2. 같은 계정의 [Access Tokens](https://huggingface.co/settings/tokens)에서 새 토큰을 만듭니다. **Read** 권한이면 다운로드할 수 있습니다. Fine-grained를 쓰면 Community-1을 읽을 수 있는 권한을 부여하세요. Write나 유료 추론 권한은 필요하지 않습니다. [토큰 권한 안내](https://huggingface.co/docs/hub/security-tokens).
3. 서버 Mac 터미널에서 아래 명령을 실행하고 토큰을 붙여넣습니다. 입력 내용은 화면에 표시되지 않으며 셸 명령 이력에 토큰을 넣지 않습니다.

```sh
cd /YOUR_SOURCE_DIR/meetingbot
./scripts/setup-hf.sh
```

`.env`에 HF_TOKEN만 추가/수정하고 기존 Tailscale 설정은 유지합니다. 파일 권한은 0600입니다. HF 토큰은 앱의 접속 키 입력 칸이나 채팅에 넣지 마세요.

4. 모델을 내려받습니다.

```sh
cd /YOUR_SOURCE_DIR/meetingbot/backend
uv run --extra speech python ../scripts/prepare_models.py --diarization
```

5. 실행 중인 서버를 다시 시작합니다. macOS 상시 서비스를 설치했다면 프로젝트 루트에서 `backend/.venv/bin/python scripts/service.py restart`를 실행합니다. 이 명령은 소스의 설정을 서비스 실행본에도 반영합니다. 서버 재시작 후 `/health`의 diar.ready와 화면의 화자 분석 준비됨 표시를 확인합니다. 다운로드 완료만으로 실제 화자 분리 품질을 검증한 것은 아닙니다.

401은 토큰/로그인 계정을, 403 또는 GatedRepoError는 모델 조건 동의·승인 상태·토큰 읽기 권한을 확인하세요. 서버는 준비된 모델을 오프라인 모드로 읽습니다.

## 다른 기기에서 접속

아래 설정을 완료하고 다른 기기를 동일한 Tailscale 네트워크에 연결한 뒤 본인 서버 주소를 엽니다.

- IP 진입 주소: `http://YOUR_TAILSCALE_IP:8765/`
- HTTPS 실행 주소: `https://YOUR_DEVICE.YOUR_TAILNET.ts.net/`

IP 주소는 HTTPS 실행 주소로 이동합니다. 브라우저 마이크는 HTTPS에서 사용합니다. 해당 Mac의 Tailscale 이름이 바뀌면 `.env`의 host/origin과 Serve 설정도 갱신해야 합니다.

접속 키를 포함한 링크가 필요하면 서버 Mac에서 실행하세요.

```sh
cd /YOUR_SOURCE_DIR/meetingbot
./scripts/access-link.sh
```

출력된 링크를 본인의 다른 기기에서 열면 접속 키를 자동 적용합니다. 이 키는 전사 기록 읽기/수정/삭제 권한이 있으므로 본인이 사용할 기기에만 전달하세요. **HF 토큰과 워크스페이스 접속 키는 서로 다릅니다.**

Tailscale은 원격 기기와 서버 Mac 사이의 연결을 제공합니다. 마이크 음성은 접속한 기기에서 서버 Mac으로 전송되고, 모델 추론은 서버 Mac에서 수행합니다. 서버 Mac이 켜져 있고 잠자기 상태가 아니어야 하며, Tailscale과 STT 서버가 실행 중이어야 합니다. Tailscale 접근 제어 정책이 제한적이면 이 장치의 TCP 443/8765 접근도 허용되어야 합니다.

## 적용 구조와 관리

```text
다른 Tailscale 기기
  ├─ http://YOUR_TAILSCALE_IP:8765 → TCP 전달 → HTTPS 주소로 307 이동
  └─ https://YOUR_DEVICE.YOUR_TAILNET.ts.net:443
       → Tailscale Serve TLS 종료
       → 127.0.0.1:8765 FastAPI + React + WebSocket
```

API는 127.0.0.1에 계속 바인딩합니다. 아래 구성은 Tailscale Serve로 tailnet에 공개합니다. Funnel은 필요하지 않습니다. [Serve 공식 문서](https://tailscale.com/docs/reference/tailscale-cli/serve).

`.env.example`의 Tailscale 항목을 참고해 `.env`에 `STT_PUBLIC_ORIGIN`, `STT_ALLOWED_HOSTS`, `STT_REDIRECT_HOSTS`를 설정하고 `STT_ORIGINS`에 정확한 HTTPS Origin을 추가한 뒤 서버를 다시 시작합니다. hostname과 IP는 본인 서버의 값이어야 합니다. 원격에서도 HTTP API와 WebSocket 접속 키 인증을 유지합니다. 임의 Origin과 Host는 거절합니다.

Serve 설정 조회:

```sh
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve status
```

아래 포트를 회의봇 전용으로 등록한 경우 원격 접속을 끄려면 해당 두 리스너를 해제합니다.

```sh
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --https=443 off
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --tcp=8765 off
```

처음 등록하거나 다시 켜려면 다음 명령을 실행합니다. 기존 Serve 상태에서 443/8765 포트가 다른 서비스에 사용 중인지 먼저 확인합니다.

```sh
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg --https=443 http://127.0.0.1:8765
/Applications/Tailscale.app/Contents/MacOS/Tailscale serve --bg --tcp=8765 tcp://127.0.0.1:8765
```

`--bg`는 Tailscale Serve 설정을 유지합니다. 별도로 macOS 상시 서비스를 설치하면 STT 앱은 LaunchAgent로 로그인 시 자동 실행되고 종료되면 자동 복구합니다. 서비스 운영은 [설치 안내](installation.md)를 참고하세요.
