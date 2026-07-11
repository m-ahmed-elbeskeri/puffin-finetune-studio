param(
    [string]$Config = "configs/data.yaml"
)
$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path "$PSScriptRoot\..").Path
Set-Location $repoRoot

$Python = $env:PYTHON
if ([string]::IsNullOrEmpty($Python)) { $Python = "python" }

function Step($label, [scriptblock]$block) {
    Write-Host "==> $label" -ForegroundColor Cyan
    & $block
    if ($LASTEXITCODE -ne 0) { throw "Step failed: $label" }
}

Step "running pipeline against $Config" {
    & $Python -m llmops.data.ingest          --config $Config
    & $Python -m llmops.data.validate        --config $Config
    & $Python -m llmops.data.redact_pii      --config $Config
    & $Python -m llmops.data.dedupe          --config $Config
    & $Python -m llmops.data.split           --config $Config
    & $Python -m llmops.data.build_dataset_card --config $Config
}

$card = (Select-String -Path $Config -Pattern '^dataset_card:\s*(.+)$' | Select-Object -First 1).Matches[0].Groups[1].Value
if ([string]::IsNullOrEmpty($card)) { $card = "dataset_cards/generated.md" }

if (Test-Path $card) {
    $version = (Select-String -Path $card -Pattern 'Version:\*\*\s+`([^`]+)`' | Select-Object -First 1).Matches[0].Groups[1].Value
    Write-Host "==> dataset version: $version" -ForegroundColor Green
    Write-Host "==> see $card for full details"
} else {
    Write-Error "dataset card $card was not generated"
    exit 1
}
