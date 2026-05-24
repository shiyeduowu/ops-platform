param(
    [string]$PsqlPath = "psql",
    [string]$HostAddress = "127.0.0.1",
    [int]$Port = 5432,
    [string]$AdminUser = "postgres",
    [string]$DatabaseName = "ops_platform",
    [string]$AppUser = "ops_user",
    [string]$AppPassword = "ops_password"
)

$ErrorActionPreference = "Stop"

Write-Host "Creating PostgreSQL user/database if needed..." -ForegroundColor Cyan
& $PsqlPath -h $HostAddress -p $Port -U $AdminUser -d postgres -c "DO `$`$ BEGIN IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '$AppUser') THEN CREATE ROLE $AppUser LOGIN PASSWORD '$AppPassword'; END IF; END `$`$;"

$dbExists = & $PsqlPath -h $HostAddress -p $Port -U $AdminUser -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname = '$DatabaseName';"
if (($dbExists | Out-String).Trim() -ne "1") {
    & $PsqlPath -h $HostAddress -p $Port -U $AdminUser -d postgres -c "CREATE DATABASE $DatabaseName OWNER $AppUser;"
} else {
    Write-Host "Database $DatabaseName already exists." -ForegroundColor Yellow
}

Write-Host "DATABASE_URL=postgresql+asyncpg://$AppUser:$AppPassword@$HostAddress`:$Port/$DatabaseName" -ForegroundColor Green
