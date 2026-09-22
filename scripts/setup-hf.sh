#!/bin/zsh
set -euo pipefail
project_dir="${0:A:h:h}"
exec "$project_dir/backend/.venv/bin/python" "$project_dir/scripts/setup_hf.py"
