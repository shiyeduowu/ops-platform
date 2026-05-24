$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$FrontendDir = Join-Path $Root "frontend"

Push-Location $FrontendDir
npm install
npm run build
Pop-Location

Write-Host "Console build output: $Root\server\static" -ForegroundColor Green

