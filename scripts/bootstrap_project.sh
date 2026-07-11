#!/usr/bin/env bash
# Bootstrap a fresh clone — creates the venv, installs dev extras, copies
# .env, runs lint + fast tests so the smoke loop is ready immediately.

set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

if ! command -v uv >/dev/null 2>&1; then
  echo "[bootstrap] uv not found — install from https://docs.astral.sh/uv/"
  echo "[bootstrap] or run:  pip install -e \".[data,eval,dev]\""
  exit 1
fi

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "[bootstrap] copied .env.example → .env"
fi

echo "[bootstrap] creating venv (.venv)"
uv venv .venv

echo "[bootstrap] installing data + eval + dev extras"
uv pip install -e ".[data,eval,dev]"

echo "[bootstrap] running ruff + fast tests"
uv run ruff check src tests
uv run pytest tests -m "not gpu and not network and not slow and not integration" -x -q

cat <<'EOF'

Done. Next steps:
  1. Drop training JSONL in data/raw/ and list it in configs/data.yaml
  2. Build dataset:       make data-build  (or .\make.ps1 data-build on Windows)
  3. Smoke train:         make train-smoke
  4. Run evals:           make evaluate
  5. Apply gate:          make gate
  6. Start serving app:   make serve
EOF
