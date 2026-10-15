#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="$root/demo-node/.venv/bin/python"

if [ ! -x "$python_bin" ]; then
  echo "Missing P4P local runtimes. Run scripts/bootstrap-local.sh first." >&2
  exit 1
fi

cd "$root"

bash scripts/public-audit.sh
"$python_bin" -m compileall -q \
  demo-node/app/demo_node \
  pilot-node/app/pilot_node \
  registry \
  p4p_core \
  scripts \
  node-control

echo "P4P local baseline is green."
