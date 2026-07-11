param(
    [Parameter(Mandatory=$true)][string]$Env,
    [Parameter(Mandatory=$true)][string]$Name,
    [Parameter(Mandatory=$true)][string]$Version
)
$ErrorActionPreference = "Stop"

if ($Env -ne "staging" -and $Env -ne "production") {
    throw "Env must be 'staging' or 'production'"
}

$Python = $env:PYTHON
if ([string]::IsNullOrEmpty($Python)) { $Python = "python" }

$backend = $env:PUFFIN_REGISTRY_BACKEND
if ([string]::IsNullOrEmpty($backend)) { $backend = "mlflow" }

$gateReport = $env:PUFFIN_GATE_REPORT
if ([string]::IsNullOrEmpty($gateReport)) { $gateReport = "artifacts/eval/gate_report.json" }

if (Test-Path $gateReport) {
    $report = Get-Content $gateReport -Raw | ConvertFrom-Json
    if (-not $report.passed) {
        throw "Refusing to promote: gate report at $gateReport shows passed=$($report.passed)"
    }
} else {
    Write-Host "WARN: no gate report at $gateReport - running gate now" -ForegroundColor Yellow
    & $Python -m llmops.evaluation.gate --config configs/eval.yaml --metrics artifacts/eval/metrics.json
}

Write-Host "==> promoting $Name v$Version -> $Env  (backend=$backend)" -ForegroundColor Cyan
$pyScript = @"
from llmops.providers.factory import get_registry
get_registry({"registry": {"backend": "$backend"}}).promote(
    name="$Name", version="$Version", alias="$Env",
)
"@
& $Python -c $pyScript
Write-Host "==> done" -ForegroundColor Green
