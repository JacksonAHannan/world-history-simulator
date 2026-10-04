#!/usr/bin/env bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$task_root"
if [[ -x "$task_root/.venv/bin/python" ]]; then
  task_python="$task_root/.venv/bin/python"
else
  task_python="$(command -v python3)"
fi
exec "$task_python" -m worldsim serve --runs-dir "$task_root/runs" "$@"
