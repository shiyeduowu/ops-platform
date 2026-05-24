$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
$DistDir = Join-Path $Root "dist"
$StageDir = Join-Path $DistDir "stage"
$ServerStage = Join-Path $StageDir "ops-platform-server"
$AgentStage = Join-Path $StageDir "ops-platform-agent"

& (Join-Path $PSScriptRoot "build-console.ps1")

if (Test-Path $StageDir) {
    Remove-Item -LiteralPath $StageDir -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ServerStage, $AgentStage | Out-Null

Copy-Item -Recurse -Force (Join-Path $Root "server\ops_platform") (Join-Path $ServerStage "ops_platform")
Copy-Item -Recurse -Force (Join-Path $Root "server\static") (Join-Path $ServerStage "static")
Copy-Item -Force (Join-Path $Root "server\app.py") (Join-Path $ServerStage "app.py")
Copy-Item -Force (Join-Path $Root "server\requirements.txt") (Join-Path $ServerStage "requirements.txt")
Copy-Item -Force (Join-Path $Root "server\schema.sql") (Join-Path $ServerStage "schema.sql")
Copy-Item -Force (Join-Path $Root "README.md") (Join-Path $ServerStage "README.md")
Copy-Item -Force (Join-Path $Root "README.zh-CN.md") (Join-Path $ServerStage "README.zh-CN.md")
Copy-Item -Force (Join-Path $Root "scripts\start-server.ps1") (Join-Path $ServerStage "start-server.ps1")
Copy-Item -Force (Join-Path $Root "scripts\create-postgres-db.ps1") (Join-Path $ServerStage "create-postgres-db.ps1")

Copy-Item -Force (Join-Path $Root "agent\agent.py") (Join-Path $AgentStage "agent.py")
Copy-Item -Force (Join-Path $Root "agent\state_store.py") (Join-Path $AgentStage "state_store.py")
Copy-Item -Force (Join-Path $Root "agent\requirements.txt") (Join-Path $AgentStage "requirements.txt")
Copy-Item -Force (Join-Path $Root "scripts\start-agent.ps1") (Join-Path $AgentStage "start-agent.ps1")

$AgentReadme = @'
# Ops Platform Agent 客户端

运行：

```powershell
python -m pip install -r requirements.txt
python agent.py --server http://SERVER_IP:8000 --activation-code OPS-DEMO --data-dir .\data
```

本地状态页：

```text
http://127.0.0.1:17680/local/status
```

也可以直接执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-agent.ps1 -ServerUrl http://SERVER_IP:8000 -ActivationCode OPS-DEMO
```
'@
$AgentReadme | Set-Content -Encoding UTF8 (Join-Path $AgentStage "README.md")

$ServerZip = Join-Path $DistDir "ops-platform-server.zip"
$AgentZip = Join-Path $DistDir "ops-platform-agent.zip"
if (Test-Path $ServerZip) { Remove-Item -LiteralPath $ServerZip -Force }
if (Test-Path $AgentZip) { Remove-Item -LiteralPath $AgentZip -Force }

Compress-Archive -Path (Join-Path $ServerStage "*") -DestinationPath $ServerZip
Compress-Archive -Path (Join-Path $AgentStage "*") -DestinationPath $AgentZip

Write-Host "Created $ServerZip" -ForegroundColor Green
Write-Host "Created $AgentZip" -ForegroundColor Green
