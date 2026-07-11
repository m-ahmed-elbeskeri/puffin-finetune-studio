#!/usr/bin/env bash
# End-to-end local smoke: data → smoke train → evaluate → gate.
# Uses the shipped example dataset and the echo eval backend.

set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

export PUFFIN_TRACKING_BACKEND="${PUFFIN_TRACKING_BACKEND:-none}"
export PUFFIN_EVAL_BACKEND="${PUFFIN_EVAL_BACKEND:-echo}"

PY="${PYTHON:-python}"

echo "==> data pipeline"
$PY -m llmops.data.ingest          --config configs/data.yaml
$PY -m llmops.data.validate        --config configs/data.yaml
$PY -m llmops.data.redact_pii      --config configs/data.yaml
$PY -m llmops.data.dedupe          --config configs/data.yaml
$PY -m llmops.data.split           --config configs/data.yaml
$PY -m llmops.data.build_dataset_card --config configs/data.yaml

if [ "${PUFFIN_SKIP_TRAIN:-0}" = "0" ]; then
  echo "==> training smoke (CPU)"
  $PY -m llmops.training.train_sft_lora --config configs/train.yaml --smoke-test
else
  echo "==> skipping training (PUFFIN_SKIP_TRAIN=1)"
fi

echo "==> eval suite (echo backend)"
$PY -m llmops.evaluation.task_eval       --config configs/eval.yaml
$PY -m llmops.evaluation.safety_eval     --config configs/eval.yaml
$PY -m llmops.evaluation.regression_eval --config configs/eval.yaml
$PY -m llmops.evaluation.latency_eval    --config configs/eval.yaml

echo "==> promotion gate"
$PY -m llmops.evaluation.gate --config configs/eval.yaml --metrics artifacts/eval/metrics.json

echo "==> SMOKE OK"
