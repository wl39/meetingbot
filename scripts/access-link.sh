#!/bin/zsh
set -euo pipefail
project_dir="${0:A:h:h}"
cd "$project_dir/backend"
exec .venv/bin/python -c 'from app.modules.stt.settings import Settings; s=Settings(); s.prepare(); print((s.public_origin or "http://127.0.0.1:8765") + "/#token=" + s.local_token())'
