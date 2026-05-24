# Ops Platform

Commercial distributed ops SaaS MVP with an outbound-only Agent and a FastAPI control plane.

## Current Scope

- Multi-tenant base tables: tenants, users, agents, agent_configs, alerts, logs, licenses.
- Activation-code based Agent registration.
- HMAC signed Agent requests.
- Heartbeat with Device Shadow config pull.
- Logs and alerts ingestion.
- WebSocket stream at `/ws/agent/{agent_id}` for metrics, logs, alerts, and config events.
- Local SQLite default for development, PostgreSQL-ready schema in `server/schema.sql`.

## Run Backend

```powershell
cd F:\py_agent\ops-platform\server
python -m pip install -r requirements.txt
python app.py
```

Or from the project root:

```powershell
.\scripts\start-server.ps1
```

Default development values:

- Admin username: `admin`
- Admin password: `admin123456`
- Agent activation code: `OPS-DEMO`
- Server URL: `http://127.0.0.1:8000`

Production deployments should override:

- `DATABASE_URL`
- `JWT_SECRET_KEY`
- `SERVER_PUBLIC_URL`
- `DEFAULT_ADMIN_USERNAME`
- `DEFAULT_ADMIN_PASSWORD`
- `DEFAULT_ACTIVATION_CODE`

## Run Agent

```powershell
cd F:\py_agent\ops-platform\agent
python -m pip install -r requirements.txt
python agent.py --server http://127.0.0.1:8000 --activation-code OPS-DEMO --data-dir .\data
```

Or from the project root:

```powershell
.\scripts\start-agent.ps1 -ServerUrl http://127.0.0.1:8000 -ActivationCode OPS-DEMO
```

The Agent stores only local credentials, config cache, alert state, and log tail offsets. Authoritative config lives in `agent_configs` on the server.

## Web Console

```powershell
cd F:\py_agent\ops-platform\frontend
npm install
npm run build
```

The build is written to `server/static`, so the backend serves the console at:

```text
http://127.0.0.1:8000
```

For frontend development:

```powershell
cd F:\py_agent\ops-platform\frontend
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

## PostgreSQL Demo

If PostgreSQL is installed and `psql` is available:

```powershell
.\scripts\create-postgres-db.ps1 -AppUser ops_user -AppPassword ops_password
.\scripts\start-server.ps1 -DatabaseUrl "postgresql+asyncpg://ops_user:ops_password@127.0.0.1:5432/ops_platform"
```

If `psql` is not in PATH, pass `-PsqlPath "C:\Program Files\PostgreSQL\16\bin\psql.exe"`.

## Build Copyable Packages

```powershell
.\scripts\package.ps1
```

Outputs:

- `dist\ops-platform-server.zip`
- `dist\ops-platform-agent.zip`
