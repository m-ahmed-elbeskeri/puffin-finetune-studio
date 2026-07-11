#!/usr/bin/env bash
# Puffin Copilot — one-shot dev launcher (bash / WSL / macOS).
#
# Runs the FastAPI backend on :8765 and the Next.js dev server on :3000.
# Output from both is interleaved with prefixes; Ctrl+C stops both.
#
# Usage:
#   export ANTHROPIC_API_KEY=sk-ant-...
#   ./copilot/scripts/dev.sh

set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(dirname "$(dirname "$SCRIPT_DIR")")

BACKEND_PORT=${PUFFIN_COPILOT_PORT:-8765}
FRONTEND_PORT=${PUFFIN_FRONTEND_PORT:-3000}

if [ -z "${ANTHROPIC_API_KEY:-}" ]; then
  echo "WARNING: ANTHROPIC_API_KEY not set — /api/chat will refuse." >&2
fi

export PYTHONUTF8=1
export PUFFIN_COPILOT_PORT=$BACKEND_PORT
export PUFFIN_COPILOT_BACKEND="http://127.0.0.1:$BACKEND_PORT"

cleanup() {
  echo "stopping…" >&2
  kill 0 2>/dev/null || true
}
trap cleanup EXIT INT TERM

(
  cd "$ROOT"
  python -m copilot.backend.main --reload 2>&1 | sed -u 's/^/[backend] /'
) &

(
  cd "$ROOT/copilot/frontend"
  npx next dev -p "$FRONTEND_PORT" 2>&1 | sed -u 's/^/[front]  /'
) &

echo ""
echo "Frontend: http://localhost:$FRONTEND_PORT"
echo "Backend:  http://localhost:$BACKEND_PORT/healthz"
echo "Press Ctrl+C to stop."

wait
