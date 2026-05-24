# Ops Platform 简体中文演示版

这是一个“内网 Agent + 公网控制台”的分布式运维 SaaS MVP。

## 本机演示

启动服务端：

```powershell
cd F:\py_agent\ops-platform
powershell -ExecutionPolicy Bypass -File .\scripts\start-server.ps1
```

启动 Agent：

```powershell
cd F:\py_agent\ops-platform
powershell -ExecutionPolicy Bypass -File .\scripts\start-agent.ps1 -ServerUrl http://127.0.0.1:8000 -ActivationCode OPS-DEMO
```

打开控制台：

```text
http://127.0.0.1:8000
```

默认账号：

```text
admin / admin123456
```

默认激活码：

```text
OPS-DEMO
```

Agent 本地状态页：

```text
http://127.0.0.1:17680/local/status
```

## PostgreSQL 部署

如果服务器已经安装 PostgreSQL，并且 `psql` 在 PATH 中：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-postgres-db.ps1 `
  -AppUser ops_user `
  -AppPassword ops_password
```

然后启动服务端：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-server.ps1 `
  -DatabaseUrl "postgresql+asyncpg://ops_user:ops_password@127.0.0.1:5432/ops_platform" `
  -ServerPublicUrl "http://服务器IP:8000" `
  -JwtSecretKey "请换成一串足够长的随机密钥" `
  -AdminUsername "admin" `
  -AdminPassword "请换成强密码" `
  -ActivationCode "OPS-DEMO"
```

如果 `psql` 不在 PATH 中，请传入完整路径：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\create-postgres-db.ps1 `
  -PsqlPath "C:\Program Files\PostgreSQL\16\bin\psql.exe"
```

## 客户机器安装 Agent

把 `ops-platform-agent.zip` 解压到客户机器后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-agent.ps1 `
  -ServerUrl "http://服务器IP:8000" `
  -ActivationCode "OPS-DEMO"
```

Agent 只需要能主动访问服务端地址，不需要开放客户内网端口。

## 重新打包

```powershell
cd F:\py_agent\ops-platform
powershell -ExecutionPolicy Bypass -File .\scripts\package.ps1
```

输出文件：

- `dist\ops-platform-server.zip`
- `dist\ops-platform-agent.zip`

