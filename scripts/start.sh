#!/bin/zsh
set -euo pipefail
project_dir="${0:A:h:h}"
export PATH="/opt/homebrew/bin:$PATH"
cd "$project_dir/backend"
if [[ "${1:-}" == "--demo" ]]; then
  shift
  exec python3 "$project_dir/scripts/demo.py" "$@"
fi
if [[ ! -x .venv/bin/python ]]; then
  uv sync --python 3.12 --extra speech
fi
if [[ ! -d "$project_dir/frontend/dist" ]]; then
  (cd "$project_dir/frontend" && npm ci --cache ../.runtime/npm-cache && npm run build)
fi
if [[ "${1:-}" == "--fake" ]]; then
  export STT_ENGINE=fake
  export STT_DATA_DIR="$project_dir/.runtime/fake"
fi
# Prefer the persistent service once installed; never start a second API on its port.
service_plist="$HOME/Library/LaunchAgents/com.meetingbot.stt.plist"
if [[ -f "$service_plist" ]]; then
  if [[ "${1:-}" == "--fake" ]]; then
    if launchctl print "gui/$(id -u)/com.meetingbot.stt" >/dev/null 2>&1; then
      print "상시 서비스가 실행 중입니다. 먼저 scripts/service.py stop으로 중지한 뒤 모의 실행하세요."
      exit 1
    fi
  else
    if ! launchctl print "gui/$(id -u)/com.meetingbot.stt" >/dev/null 2>&1; then
      .venv/bin/python "$project_dir/scripts/service.py" install
    fi
    print "STT 상시 서비스가 실행 중입니다. 변경 적용: backend/.venv/bin/python scripts/service.py restart"
    "$project_dir/scripts/access-link.sh"
    exit 0
  fi
fi
export PYANNOTE_METRICS_ENABLED=0
.venv/bin/python -c 'from app.modules.stt.settings import Settings; s=Settings(); s.prepare(); print("Open locally: http://127.0.0.1:8765/#token=" + s.local_token()); print("Remote access link: run ./scripts/access-link.sh from the project root") if s.public_origin else None'
exec .venv/bin/python -m uvicorn app.main:create_app --factory --host 127.0.0.1 --port 8765 --ws-max-size 500000 --ws-max-queue 8
