#!/bin/zsh
set -euo pipefail
project_dir="${0:A:h:h}"
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
cd "$project_dir"
exec backend/.venv/bin/python scripts/demo.py --public
