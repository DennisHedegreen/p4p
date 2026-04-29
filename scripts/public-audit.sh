#!/usr/bin/env bash
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

echo "== branch =="
git branch --show-current

echo
echo "== working tree =="
git status --short

echo
echo "== whitespace =="
git diff --check

echo
echo "== tracked sensitive filenames =="
sensitive_files="$(
  git ls-files |
    grep -Ei '(^|/)(\.env|\.env\..*|.*\.(sqlite|sqlite3|db|pem|key|p12|pfx)|.*(secret|credential|password|private).*)$' || true
)"

if [ -n "$sensitive_files" ]; then
  echo "$sensitive_files"
  echo "Refusing public release: tracked sensitive-looking filenames found." >&2
  exit 1
fi

echo "none"

echo
echo "== hard secret literal scan =="
if command -v rg >/dev/null 2>&1; then
  hard_matches="$(
    rg -n --hidden --glob '!.git/**' --glob '!__pycache__/**' --glob '!*.pyc' \
      --glob '!.venv/**' --glob '!registry/.venv/**' --glob '!demo-node/.venv/**' \
      --glob '!pilot-node/.venv/**' --glob '!lab/.venv/**' --glob '!.pytest_cache/**' \
      --glob '!scripts/public-audit.sh' \
      --regexp '-----BEGIN ([A-Z0-9 ]+ )?PRIVATE KEY-----' \
      --regexp 'ghp_[A-Za-z0-9]{36,}' \
      --regexp 'github_pat_[A-Za-z0-9_]{40,}' \
      --regexp 'AKIA[0-9A-Z]{16}' \
      --regexp 'AIza[0-9A-Za-z_-]{35}' \
      --regexp 'sk-[A-Za-z0-9]{32,}' \
      . || true
  )"
else
  hard_matches=""
  echo "rg not found; skipped hard literal scan"
fi

if [ -n "$hard_matches" ]; then
  echo "$hard_matches"
  echo "Refusing public release: hard secret-looking literals found." >&2
  exit 1
fi

echo "none"

echo
echo "== review-only keyword scan =="
if command -v rg >/dev/null 2>&1; then
  rg -n --hidden --glob '!.git/**' --glob '!__pycache__/**' --glob '!*.pyc' \
    --glob '!.venv/**' --glob '!registry/.venv/**' --glob '!demo-node/.venv/**' \
    --glob '!pilot-node/.venv/**' --glob '!lab/.venv/**' --glob '!.pytest_cache/**' \
    --glob '!scripts/public-audit.sh' \
    --regexp 'secret|token|password|credential|private key|journalist|outreach|strategy|LifeOS' \
    . || true
else
  echo "rg not found; skipped review-only keyword scan"
fi

echo
echo "== javascript syntax =="
if command -v node >/dev/null 2>&1; then
  node --check client/app.js
else
  echo "node not found; skipped"
fi

echo
echo "== python tests =="
if [ -x demo-node/.venv/bin/python ]; then
  demo-node/.venv/bin/python -m unittest discover -s tests -q
else
  echo "demo-node/.venv/bin/python not found; skipped"
fi

echo
echo "Public audit completed."
