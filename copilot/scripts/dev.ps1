# Puffin Copilot - one-shot dev launcher (Windows PowerShell).
#
# Runs the FastAPI backend on :8765 and the Next.js dev server on :3000,
# both in the same console with prefixed output. Ctrl+C stops both.
#
# Usage:
#   $env:ANTHROPIC_API_KEY="sk-ant-..."
#   ./copilot/scripts/dev.ps1
#
# Optional:
#   $env:PUFFIN_COPILOT_ENABLE_DANGEROUS="1"   # unlock state-mutating tools

param(
  [int]$BackendPort = 8765,
  [int]$FrontendPort = 3000
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent | Split-Path -Parent

if (-not $env:ANTHROPIC_API_KEY) {
  Write-Warning "ANTHROPIC_API_KEY is not set - the /api/chat endpoint will refuse."
}

$env:PYTHONUTF8 = "1"
$env:PUFFIN_COPILOT_PORT = $BackendPort
$env:PUFFIN_COPILOT_BACKEND = "http://127.0.0.1:$BackendPort"

Write-Host "==> backend on :$BackendPort (hot reload)" -ForegroundColor Yellow
$backend = Start-Process -PassThru -NoNewWindow `
  -FilePath python `
  -ArgumentList @("-m", "copilot.backend.main", "--reload") `
  -WorkingDirectory $root

Write-Host "==> frontend on :$FrontendPort" -ForegroundColor Yellow
$frontend = Start-Process -PassThru -NoNewWindow `
  -FilePath "cmd" `
  -ArgumentList @("/c", "npx", "next", "dev", "--turbo", "-p", $FrontendPort) `
  -WorkingDirectory (Join-Path $root "copilot/frontend")

Write-Host ""
Write-Host "Frontend: http://localhost:$FrontendPort"
Write-Host "Backend:  http://localhost:$BackendPort/healthz"
Write-Host "Press Ctrl+C to stop both."

try {
  Wait-Process -Id $backend.Id, $frontend.Id
}
finally {
  if ($backend -and -not $backend.HasExited) { Stop-Process -Id $backend.Id -Force }
  if ($frontend -and -not $frontend.HasExited) { Stop-Process -Id $frontend.Id -Force }
}
