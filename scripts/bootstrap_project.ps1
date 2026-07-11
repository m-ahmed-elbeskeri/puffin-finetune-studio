param()
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$uv = Get-Command uv -ErrorAction SilentlyContinue
if ($null -eq $uv) {
    Write-Host "[bootstrap] uv not found. Install from https://docs.astral.sh/uv/"
    Write-Host "[bootstrap] or run:  python -m pip install -e `".[data,eval,dev]`""
    exit 1
}

if (-not (Test-Path ".env") -and (Test-Path ".env.example")) {
    Copy-Item .env.example .env
    Write-Host "[bootstrap] copied .env.example -> .env"
}

Write-Host "[bootstrap] creating venv (.venv)"
uv venv .venv

Write-Host "[bootstrap] installing data + eval + dev extras"
uv pip install -e ".[data,eval,dev]"

Write-Host "[bootstrap] running ruff + fast tests"
uv run ruff check src tests
uv run pytest tests -m "not gpu and not network and not slow and not integration" -x -q

Write-Host ""
Write-Host "Done. Next steps:"
Write-Host "  1. Drop training JSONL in data/raw/ and list it in configs/data.yaml"
Write-Host "  2. Build dataset:       .\make.ps1 data-build"
Write-Host "  3. Smoke train:         .\make.ps1 train-smoke"
Write-Host "  4. Run evals:           .\make.ps1 evaluate"
Write-Host "  5. Apply gate:          .\make.ps1 gate"
Write-Host "  6. Start serving app:   .\make.ps1 serve"
