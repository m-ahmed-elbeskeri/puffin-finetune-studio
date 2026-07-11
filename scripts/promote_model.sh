#!/usr/bin/env bash
# Promote a model to the given environment (staging | production).
#   ./scripts/promote_model.sh staging  customer-support-llm  3
# Reads PUFFIN_REGISTRY_BACKEND (default: mlflow).

set -euo pipefail

env="${1:-}"
name="${2:-}"
version="${3:-}"
backend="${PUFFIN_REGISTRY_BACKEND:-mlflow}"

if [ -z "$env" ] || [ -z "$name" ] || [ -z "$version" ]; then
  echo "Usage: $0 <env> <model_name> <version>"
  exit 2
fi
if [ "$env" != "staging" ] && [ "$env" != "production" ]; then
  echo "env must be 'staging' or 'production'"
  exit 2
fi

PY="${PYTHON:-python}"

# Read gate result first — never promote a model that didn't pass the gate.
gate_report="${PUFFIN_GATE_REPORT:-artifacts/eval/gate_report.json}"
if [ -f "$gate_report" ]; then
  passed="$(jq -r .passed "$gate_report" 2>/dev/null || echo "")"
  if [ "$passed" != "true" ]; then
    echo "Refusing to promote: gate report at $gate_report shows passed=$passed"
    exit 3
  fi
else
  echo "WARN: no gate report at $gate_report — running gate now"
  $PY -m llmops.evaluation.gate --config configs/eval.yaml --metrics artifacts/eval/metrics.json
fi

echo "==> promoting $name v$version → $env  (backend=$backend)"
$PY - <<PY
from llmops.providers.factory import get_registry
get_registry({"registry": {"backend": "${backend}"}}).promote(
    name="${name}", version="${version}", alias="${env}",
)
PY
echo "==> done"
