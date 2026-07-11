#!/usr/bin/env bash
# Run the data pipeline and tag the produced dataset by its content hash.

set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

PY="${PYTHON:-python}"
config="${1:-configs/data.yaml}"

echo "==> running pipeline against $config"
$PY -m llmops.data.ingest          --config "$config"
$PY -m llmops.data.validate        --config "$config"
$PY -m llmops.data.redact_pii      --config "$config"
$PY -m llmops.data.dedupe          --config "$config"
$PY -m llmops.data.split           --config "$config"
$PY -m llmops.data.build_dataset_card --config "$config"

card="$(awk '/dataset_card:/ {print $2}' "$config")"
card="${card:-dataset_cards/generated.md}"

if [ -f "$card" ]; then
  version="$(awk -F'`' '/Version:/ {print $2; exit}' "$card")"
  echo "==> dataset version: $version"
  echo "==> see $card for full details"
else
  echo "==> dataset card $card was not generated"
  exit 1
fi
