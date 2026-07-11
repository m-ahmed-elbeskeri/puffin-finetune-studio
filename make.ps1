<#
PowerShell equivalent of the Makefile for Windows users without GNU make.
Usage:  .\make.ps1 <target> [-Profile local] [-Env dev]
        .\make.ps1 help
#>
param(
    [Parameter(Position = 0)]
    [string]$Target = "help",
    [string]$Profile = "local",
    [string]$Env = "dev"
)

$ErrorActionPreference = "Stop"
$Python = $env:PYTHON
if ([string]::IsNullOrEmpty($Python)) { $Python = "python" }

function Invoke-Step($Description, [scriptblock]$Block) {
    Write-Host "==> $Description" -ForegroundColor Cyan
    & $Block
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Description (exit $LASTEXITCODE)"
    }
}

switch ($Target) {
    "help" {
        Write-Host "puffin-finetune-studio - PowerShell targets"
        Write-Host ""
        Write-Host "  setup            Create venv + install dev deps (uv)"
        Write-Host "  install          Install editable package"
        Write-Host "  install-train    Install with [train] extras"
        Write-Host "  install-serve    Install with [serve] extras"
        Write-Host "  install-all      Install with [all,dev] extras"
        Write-Host "  lint             Ruff + mypy"
        Write-Host "  typecheck        mypy on src/llmops"
        Write-Host "  format           Auto-format + auto-fix"
        Write-Host "  test             Run pytest with coverage"
        Write-Host "  test-fast        Run only fast unit tests"
        Write-Host "  data-validate    Validate raw data"
        Write-Host "  data-build       Run full data pipeline"
        Write-Host "  train-smoke      Tiny CPU smoke train"
        Write-Host "  train            Real train"
        Write-Host "  evaluate         Run all evals"
        Write-Host "  gate             Apply promotion gate"
        Write-Host "  serve            Start serving app"
        Write-Host "  clean            Remove caches and artifacts"
    }
    "setup" {
        Invoke-Step "Creating venv and installing dev extras" {
            uv venv .venv
            uv pip install -e ".[data,eval,dev]"
        }
    }
    "install"       { Invoke-Step "Install (no extras)"        { & $Python -m pip install -e . } }
    "install-train" { Invoke-Step "Install with [train]"       { & $Python -m pip install -e ".[train,data,eval,mlflow]" } }
    "install-serve" { Invoke-Step "Install with [serve]"       { & $Python -m pip install -e ".[serve]" } }
    "install-eval"  { Invoke-Step "Install with [eval]"        { & $Python -m pip install -e ".[eval,data]" } }
    "install-all"   { Invoke-Step "Install with [all,dev]"     { & $Python -m pip install -e ".[all,dev]" } }
    "lint" {
        Invoke-Step "ruff check"  { ruff check src tests }
        Invoke-Step "ruff format" { ruff format --check src tests }
        Write-Host "==> mypy (warnings only)" -ForegroundColor Cyan
        mypy src/llmops
    }
    "typecheck" {
        Invoke-Step "mypy" { mypy src/llmops }
    }
    "format" {
        Invoke-Step "ruff fix"    { ruff check --fix src tests }
        Invoke-Step "ruff format" { ruff format src tests }
    }
    "test" {
        Invoke-Step "pytest" { pytest tests --cov=src/llmops --cov-report=term-missing }
    }
    "test-fast" {
        Invoke-Step "pytest fast" { pytest tests -m "not gpu and not network and not slow and not integration" -x }
    }
    "cov" {
        Invoke-Step "coverage" { pytest tests --cov=src/llmops --cov-report=html }
        Write-Host "Open htmlcov/index.html"
    }
    "data-validate" {
        Invoke-Step "validate data" { & $Python -m llmops.data.validate --config configs/data.yaml }
    }
    "data-build" {
        Invoke-Step "ingest"     { & $Python -m llmops.data.ingest --config configs/data.yaml }
        Invoke-Step "redact_pii" { & $Python -m llmops.data.redact_pii --config configs/data.yaml }
        Invoke-Step "dedupe"     { & $Python -m llmops.data.dedupe --config configs/data.yaml }
        Invoke-Step "split"      { & $Python -m llmops.data.split --config configs/data.yaml }
        Invoke-Step "card"       { & $Python -m llmops.data.build_dataset_card --config configs/data.yaml }
    }
    "train-smoke" {
        Invoke-Step "train smoke" { & $Python -m llmops.training.train_sft_lora --config configs/train.yaml --smoke-test }
    }
    "train" {
        Invoke-Step "train" { & $Python -m llmops.training.train_sft_lora --config configs/train.yaml }
    }
    "evaluate" {
        Invoke-Step "task eval"       { & $Python -m llmops.evaluation.task_eval --config configs/eval.yaml }
        Invoke-Step "safety eval"     { & $Python -m llmops.evaluation.safety_eval --config configs/eval.yaml }
        Invoke-Step "regression eval" { & $Python -m llmops.evaluation.regression_eval --config configs/eval.yaml }
        Invoke-Step "latency eval"    { & $Python -m llmops.evaluation.latency_eval --config configs/eval.yaml }
    }
    "gate" {
        Invoke-Step "gate" { & $Python -m llmops.evaluation.gate --config configs/eval.yaml --metrics artifacts/eval/metrics.json }
    }
    "serve" {
        Invoke-Step "serve" { & $Python -m llmops.serving.app --config configs/deploy.yaml }
    }
    "clean" {
        Write-Host "==> clean" -ForegroundColor Cyan
        Remove-Item -Recurse -Force .pytest_cache, .mypy_cache, .ruff_cache, htmlcov, build, dist, *.egg-info -ErrorAction SilentlyContinue
        Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "Done."
    }
    default {
        Write-Host "Unknown target: $Target"
        Write-Host "Run '.\make.ps1 help' for available targets."
        exit 2
    }
}
