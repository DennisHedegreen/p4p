#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
python_bin="${PYTHON_BIN:-python3}"
constraints="$root/requirements.lock.txt"

components=(registry demo-node lab pilot-node)

for component in "${components[@]}"; do
  component_root="$root/$component"
  venv="$component_root/.venv"

  if [ ! -x "$venv/bin/python" ]; then
    "$python_bin" -m venv "$venv"
  fi

  "$venv/bin/python" -m pip install \
    --constraint "$constraints" \
    --requirement "$component_root/requirements.txt"
done

"$root/demo-node/.venv/bin/python" -m pip install \
  --constraint "$constraints" \
  --requirement "$root/requirements-test.txt"

echo "P4P local runtimes are ready."
echo "Run scripts/check-local.sh from the repository root."
