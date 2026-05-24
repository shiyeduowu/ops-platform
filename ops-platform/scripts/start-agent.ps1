param(
    [string]$ServerUrl = "http://127.0.0.1:8000",
    [string]$ActivationCode = "OPS-DEMO",
    [string]$DataDir = ".\data"
)

$ErrorActionPreference = "Stop"
$LocalAgent = Join-Path $PSScriptRoot "agent.py"
if (Test-Path $LocalAgent) {
    $AgentDir = $PSScriptRoot
} else {
    $Root = Split-Path -Parent $PSScriptRoot
    $AgentDir = Join-Path $Root "agent"
}
$ResolvedDataDir = Join-Path $AgentDir $DataDir

Write-Host "Installing Agent requirements..." -ForegroundColor Cyan
Push-Location $AgentDir
python -m pip install -r requirements.txt

Write-Host "Starting Agent against $ServerUrl" -ForegroundColor Green
python agent.py --server $ServerUrl --activation-code $ActivationCode --data-dir $ResolvedDataDir
Pop-Location
