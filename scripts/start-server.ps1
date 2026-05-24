param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8000,
    [string]$DatabaseUrl = $env:DATABASE_URL,
    [string]$ServerPublicUrl = $env:SERVER_PUBLIC_URL,
    [string]$JwtSecretKey = $env:JWT_SECRET_KEY,
    [string]$AdminUsername = $env:DEFAULT_ADMIN_USERNAME,
    [string]$AdminPassword = $env:DEFAULT_ADMIN_PASSWORD,
    [string]$ActivationCode = $env:DEFAULT_ACTIVATION_CODE
)

$ErrorActionPreference = "Stop"
$LocalApp = Join-Path $PSScriptRoot "app.py"
if (Test-Path $LocalApp) {
    $ServerDir = $PSScriptRoot
} else {
    $Root = Split-Path -Parent $PSScriptRoot
    $ServerDir = Join-Path $Root "server"
}

if ([string]::IsNullOrWhiteSpace($DatabaseUrl)) {
    $DatabaseUrl = "sqlite+aiosqlite:///./ops_platform.db"
    Write-Host "DATABASE_URL not provided, using local SQLite demo database." -ForegroundColor Yellow
}

if ([string]::IsNullOrWhiteSpace($ServerPublicUrl)) {
    $ServerPublicUrl = "http://127.0.0.1:$Port"
}

if ([string]::IsNullOrWhiteSpace($JwtSecretKey)) {
    $JwtSecretKey = "demo-change-me-$([Guid]::NewGuid().ToString('N'))"
}

if ([string]::IsNullOrWhiteSpace($AdminUsername)) {
    $AdminUsername = "admin"
}

if ([string]::IsNullOrWhiteSpace($AdminPassword)) {
    $AdminPassword = "admin123456"
}

if ([string]::IsNullOrWhiteSpace($ActivationCode)) {
    $ActivationCode = "OPS-DEMO"
}

$env:DATABASE_URL = $DatabaseUrl
$env:SERVER_HOST = $HostAddress
$env:SERVER_PORT = "$Port"
$env:SERVER_PUBLIC_URL = $ServerPublicUrl
$env:JWT_SECRET_KEY = $JwtSecretKey
$env:DEFAULT_ADMIN_USERNAME = $AdminUsername
$env:DEFAULT_ADMIN_PASSWORD = $AdminPassword
$env:DEFAULT_ACTIVATION_CODE = $ActivationCode

Write-Host "Installing backend requirements..." -ForegroundColor Cyan
Push-Location $ServerDir
python -m pip install -r requirements.txt

Write-Host "Starting Ops Platform at http://127.0.0.1:$Port" -ForegroundColor Green
python app.py
Pop-Location
