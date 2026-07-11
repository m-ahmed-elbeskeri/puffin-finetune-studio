param([switch]$SkipTrain)
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$env:PUFFIN_TRACKING_BACKEND = $env:PUFFIN_TRACKING_BACKEND
if ([string]::IsNullOrEmpty($env:PUFFIN_TRACKING_BACKEND)) { $env:PUFFIN_TRACKING_BACKEND = "none" }
$env:PUFFIN_EVAL_BACKEND = $env:PUFFIN_EVAL_BACKEND
if ([string]::IsNullOrEmpty($env:PUFFIN_EVAL_BACKEND)) { $env:PUFFIN_EVAL_BACKEND = "echo" }

$Python = $env:PYTHON
if ([string]::IsNullOrEmpty($Python)) { $Python = "python" }

function Step($label, [scriptblock]$block) {
    Write-Host "==> $label" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "Step failed: $label" }
}

Step "data pipeline" {
    & $Python -m llmops.data.ingest          --config configs/data.yaml
    & $Python -m llmops.data.validate        --config configs/data.yaml
    & $Python -m llmops.data.redact_pii      --config configs/data.yaml
    & $Python -m llmops.data.dedupe          --config configs/data.yaml
    & $Python -m llmops.data.split           --config configs/data.yaml
    & $Python -m llmops.data.build_dataset_card --config configs/data.yaml
}

if (-not $SkipTrain) {
    Step "training smoke (CPU)" {
        & $Python -m llmops.training.train_sft_lora --config configs/train.yaml --smoke-test
    }
} else {
    Write-Host "==> skipping training (-SkipTrain set)" -ForegroundColor Yellow
}

Step "eval suite (echo backend)" {
    & $Python -m llmops.evaluation.task_eval       --config configs/eval.yaml
    & $Python -m llmops.evaluation.safety_eval     --config configs/eval.yaml
    & $Python -m llmops.evaluation.regression_eval --config configs/eval.yaml
    & $Python -m llmops.evaluation.latency_eval    --config configs/eval.yaml
}

Step "promotion gate" {
    & $Python -m llmops.evaluation.gate --config configs/eval.yaml --metrics artifacts/eval/metrics.json
}

Write-Host "==> SMOKE OK" -ForegroundColor Green
