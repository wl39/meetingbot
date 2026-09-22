# Windows 설치와 실행

Windows 10/11 x64(Intel/AMD 64비트)에서 Docker 없이 사용할 수 있습니다. Windows ARM·32비트는 현재 설치 대상이 아닙니다. 기본 음성 엔진은 **Faster Whisper CPU / int8**이며 GPU가 필요하지 않습니다. RAM 16 GB와 SSD 여유 공간 25 GB 이상을 권장합니다. Small 모델로 시작하고, 긴 회의·화자 분석을 함께 사용하려면 RAM 32 GB를 권장합니다.

## 처음 설치

1. [저장소](https://github.com/wl39/meetingbot)에서 소스를 내려받거나 Git으로 복제합니다. ZIP은 압축을 완전히 푼 뒤 실행하세요. 긴 경로 문제를 줄이려면 `C:\meetingbot`처럼 짧은 로컬 폴더를 사용합니다.
2. 프로젝트 폴더의 **`Install-Windows.cmd`**를 더블클릭합니다.
3. 설치 창을 유지합니다. Python 3.12 x64, Node.js 22 이상, FFmpeg/ffprobe를 확인하고 없는 도구는 WinGet으로 설치합니다. 기존의 호환 도구는 재사용합니다. 설치 프로그램의 권한 확인이 나타나면 내용을 확인해 진행하세요.
4. Python 가상 환경 두 개와 웹 화면을 준비하고 **`Meetingbot.cmd`**를 생성합니다. 첫 설치는 인터넷과 수 GB의 다운로드 공간이 필요합니다.
5. 브라우저가 열리면 **설정 및 관리 → 음성 인식 → Faster Whisper CPU → Small → 설치 → 사용하기**를 선택합니다.

Git으로 설치하려면 Git을 준비한 뒤 PowerShell에서 실행합니다.

```powershell
git clone https://github.com/wl39/meetingbot.git
cd meetingbot
.\Install-Windows.cmd
```

설치만 하고 앱을 시작하지 않으려면 PowerShell에서 다음을 실행합니다.

```powershell
.\Install-Windows.cmd -NoLaunch
```

WinGet 설치 명령에 사용하는 패키지는 `Python.Python.3.12`, `OpenJS.NodeJS.22`, `Gyan.FFmpeg`입니다. WinGet 자체가 없다면 Microsoft의 [App Installer / WinGet 안내](https://learn.microsoft.com/en-us/windows/package-manager/winget/)에 따라 준비하거나 아래 수동 설치를 사용하세요. 이 스크립트는 서명된 MSI/EXE 배포판이 아닌 소스 설치 도우미입니다.

## 다음 실행과 종료

프로젝트 폴더의 **`Meetingbot.cmd`**를 더블클릭합니다. STT와 자료 검색 서비스가 함께 시작되고 브라우저가 열립니다. 자동으로 열리지 않으면 [http://127.0.0.1:8765](http://127.0.0.1:8765)에 접속하세요. 관리자 로그인이 필요하면 `.runtime\local-token`의 키를 사용합니다.

실행 창을 유지해야 앱이 동작합니다. 종료할 때는 **Ctrl+C**를 누르고 종료를 기다리세요. 이 런처가 시작한 API와 음성 처리 프로세스만 정리합니다. 창을 강제로 닫으면 진행 중 작업도 강제 종료되므로 정상 종료를 권장합니다. Windows Job Object가 남은 하위 프로세스를 함께 정리하도록 구성했습니다.

자료 검색은 웹 설정에서 임베딩 모델을 설치하고 워크스페이스에 문서를 올리면 됩니다. 화자 분석 모델을 추가하려면:

```powershell
backend\.venv\Scripts\python.exe scripts\prepare_models.py --diarization-only --prompt-token
```

먼저 [Community-1](https://huggingface.co/pyannote/speaker-diarization-community-1) 접근 조건에 동의해야 합니다. 프롬프트에 입력한 Hugging Face 토큰은 저장하지 않습니다. 설치 후 런처를 다시 시작하세요.

## 수동 설치

회사 PC 정책 등으로 WinGet을 사용할 수 없다면 Python 3.12 x64, Node.js 22, FFmpeg와 ffprobe를 직접 설치하고 PATH에 등록하세요. 새 PowerShell 창에서 다음을 확인합니다.

```powershell
py -3.12 --version
node --version
npm.cmd --version
ffmpeg -version
ffprobe -version
```

프로젝트 폴더에서 실행합니다.

```powershell
py -3.12 scripts\install.py
```

설치 스크립트는 uv와 Python 실행 환경을 프로젝트 내부에 준비합니다. Python 가상 환경을 수동 활성화하거나 PowerShell 실행 정책을 시스템 전체에서 바꿀 필요는 없습니다.

## 저장 위치와 업데이트

- `.runtime\`: 전사 기록, 권한, 음성 모델, 임시 오디오와 로그
- `.rag-data\`: 문서 원본, 검색 색인과 임베딩 모델
- `.runtime\logs\backend.log`, `.runtime\logs\rag.log`: API 실행 로그

설치 후에는 프로젝트 폴더를 임의로 옮기지 마세요. 모델 manifest와 가상 환경에 절대 경로가 들어갑니다. 업데이트 전에는 정상 종료하고 데이터 폴더와 개인 설정을 백업한 다음, 변경 사항을 받은 뒤 `Install-Windows.cmd`를 다시 실행합니다. 설정과 데이터는 기존 폴더에 유지됩니다.

## 문제 해결

| 증상 | 해결 방법 |
|---|---|
| WinGet을 찾을 수 없음 | App Installer를 준비하거나 수동 설치 절차 사용 |
| Node 버전이 낮다는 안내 | Node.js 22 이상 설치 후 새 창에서 재실행 |
| `npm.ps1` 실행 정책 오류 | 수동 npm 명령은 `npm.cmd` 사용. 앱 설치기는 Node로 npm을 직접 실행 |
| FFmpeg를 설치했지만 찾지 못함 | 새 터미널에서 `ffmpeg -version`과 `ffprobe -version` 확인 |
| 토치/음성 패키지 DLL 로드 오류 | x64 Python·운영체제 확인, [Microsoft Visual C++ x64 런타임](https://learn.microsoft.com/en-us/cpp/windows/latest-supported-vc-redist) 설치 여부 확인 후 재실행 |
| 경로가 너무 길다는 오류 | 더 짧은 로컬 경로에 다시 설치. 기존 데이터는 먼저 백업 |
| 포트 8765/8766 사용 중 | 기존 회의봇 실행 창을 정상 종료한 뒤 다시 실행 |
| 전사 준비가 되지 않음 | 음성 모델 설치 후 **사용하기**를 눌렀는지 확인 |
| 마이크가 동작하지 않음 | Windows 개인정보 설정과 브라우저의 마이크 권한 확인. 로컬 주소 또는 HTTPS에서 접속 |
| 문서 경로가 거부됨 | 실제 로컬 폴더 사용. 심볼릭 링크·정션·일부 클라우드 동기화 폴더는 보호 목적으로 제외 |

## 검증 범위

macOS에서 Windows 호환 분기, 한글 처리, 오디오 파일 잠금·정리와 설치/런처 회귀 테스트를 실행합니다. [Windows 자동 테스트](../.github/workflows/windows.yml)는 Windows 러너에서 한글·공백이 들어간 폴더에 실제 패키지를 설치하고 웹 화면을 빌드한 뒤, STT/RAG 테스트와 Win32 파일 접근·프로세스 종료 테스트를 실행하도록 구성했습니다. 저장소에 push하면 자동 실행됩니다.

현재 작업 환경에는 Windows가 없어 네이티브 Windows 테스트의 성공 결과는 아직 확인하지 않았습니다. 실제 마이크, 실모델 전사 품질, 장시간 회의 성능도 별도로 확인해야 합니다. 모의 모델 회귀 테스트 통과가 이를 보장하지는 않습니다.
