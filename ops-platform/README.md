<div align="center">

# Ops Platform

**Distributed Ops Monitoring & Management SaaS**

[English](#english) | [中文](#中文)

---

A multi-tenant operations platform with an outbound-only Agent architecture.
High-frequency local detection, state-flip alerting, and a real-time control plane.

</div>

---

<a name="english"></a>

## English

### Architecture

```
┌─────────────────────────────────────────────────────┐
│                   Web Console (Vue 3)                │
│          Dashboard · Agents · Alerts · Logs          │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────────────┐
│              Control Plane (FastAPI)                 │
│   Auth · RBAC · Alerts · Notifications · Scheduler   │
│   16 API modules · WebSocket real-time push          │
└──────────────────────┬──────────────────────────────┘
                       │ Heartbeat (outbound only)
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ Agent A │   │ Agent B │   │ Agent N │
   │ :17680  │   │ :17680  │   │ :17680  │
   └─────────┘   └─────────┘   └─────────┘
   Local 30s checks: port · disk · CPU · memory
   · Windows services · Java processes · log tailing
```

### Key Features

| Module | Capabilities |
|--------|-------------|
| **Agent Monitoring** | 30s local checks, state-flip alerting, fingerprint dedup, log tailing with stack aggregation |
| **Alert Management** | Lifecycle (open/acknowledged/resolved), 5 notification channels (DingTalk, WeCom, Feishu, Email, Webhook) |
| **Remote Operations** | Shell commands, file distribution, software deployment — all via heartbeat dispatch |
| **Stress Testing** | HTTP API, browser automation, infrastructure stress — per-agent scheduling and reporting |
| **Configuration** | Device Shadow pattern, version-tracked config pull, JSON editor UI |
| **Audit & Compliance** | Full operation audit log, tenant-isolated data |

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2 |
| Frontend | Vue 3, TypeScript, Vite, Lucide Icons |
| Database | SQLite (dev) / PostgreSQL (prod) |
| Auth | JWT (PyJWT), HMAC agent signatures, bcrypt |
| Real-time | WebSocket (per-agent + dashboard channels) |

### Quick Start

#### Prerequisites

- Python 3.12+
- Node.js 18+ (for frontend build)

#### 1. Start Server

```bash
cd ops-platform/server
pip install -r requirements.txt
python app.py
```

The server auto-generates secure defaults on first run (JWT secret, admin password, activation code).
Check the console output for the generated credentials.

#### 2. Start Agent

```bash
cd ops-platform/agent
pip install -r requirements.txt
python agent.py --server http://127.0.0.1:8000 --activation-code <YOUR_ACTIVATION_CODE>
```

#### 3. Open Console

Navigate to `http://127.0.0.1:8000` and log in with the credentials from step 1.

#### 4. Build Frontend (optional)

```bash
cd ops-platform/frontend
npm install
npm run build
```

The build output goes to `server/static/` and is served automatically.

### Production Deployment

Set these environment variables before starting:

```bash
ENV=production
JWT_SECRET_KEY=<random-48-char-string>
DEFAULT_ADMIN_PASSWORD=<strong-password>
DEFAULT_ACTIVATION_CODE=<custom-code>
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ops_platform
SERVER_PUBLIC_URL=https://ops.your-domain.com
CORS_ORIGINS=https://ops.your-domain.com
```

The server **refuses to start** in production mode if secrets are not set.

### Security Highlights

- JWT secret auto-generated (dev) or required (prod) — no hardcoded defaults
- Content-Security-Policy, X-Frame-Options, HSTS headers
- SSRF protection with DNS resolution validation on webhook URLs
- Command whitelist + shell metacharacter blocking on remote execution
- Path traversal protection on file operations
- WebSocket tenant-isolation (agent ownership verified)
- Agent registration rate limiting (5/min per IP)
- Credential files excluded from version control

### Project Structure

```
ops-platform/
├── agent/                  # Outbound-only monitoring agent
│   ├── agent.py            # Core agent (1480 lines)
│   ├── remote/             # Shell, deploy, file download executors
│   └── stress/             # Stress test runners (HTTP, browser, infra)
├── server/                 # FastAPI control plane
│   ├── ops_platform/
│   │   ├── api/v1/routes/  # 16 API route modules
│   │   ├── core/           # Config, security, utils
│   │   ├── models.py       # 25 SQLAlchemy models
│   │   ├── scheduler.py    # Background patrol & alert engine
│   │   └── notifier.py     # 5 notification channels
│   └── requirements.txt
├── frontend/               # Vue 3 SPA
│   └── src/
│       ├── views/          # 18 page components
│       ├── api.ts          # API client (427 lines)
│       └── router.ts       # Route definitions
└── scripts/                # Deployment & packaging scripts
```

---

<a name="中文"></a>

## 中文

### 架构概览

```
┌─────────────────────────────────────────────────────┐
│               Web 控制台 (Vue 3)                     │
│        仪表盘 · Agent管理 · 告警 · 日志              │
└──────────────────────┬──────────────────────────────┘
                       │ HTTP / WebSocket
┌──────────────────────▼──────────────────────────────┐
│              控制平面 (FastAPI)                       │
│   认证 · 权限 · 告警 · 通知 · 调度器                  │
│   16 个 API 模块 · WebSocket 实时推送                 │
└──────────────────────┬──────────────────────────────┘
                       │ 心跳（仅出站）
        ┌──────────────┼──────────────┐
        ▼              ▼              ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ Agent A │   │ Agent B │   │ Agent N │
   │ :17680  │   │ :17680  │   │ :17680  │
   └─────────┘   └─────────┘   └─────────┘
   本地 30s 检测: 端口 · 磁盘 · CPU · 内存
   · Windows 服务 · Java 进程 · 日志采集
```

### 核心功能

| 模块 | 能力 |
|------|------|
| **Agent 监控** | 30 秒本地高频检测，状态翻转告警，指纹去重，日志尾部采集 + 堆栈聚合 |
| **告警管理** | 全生命周期（打开/确认/解决），5 种通知渠道（钉钉、企微、飞信、邮件、Webhook） |
| **远程运维** | Shell 命令、文件分发、软件部署 — 均通过心跳下发执行 |
| **压力测试** | HTTP API、浏览器自动化、基础设施压测 — 按 Agent 调度和汇报 |
| **配置管理** | 设备影子模式，版本化配置拉取，JSON 编辑器 UI |
| **审计合规** | 完整操作审计日志，租户数据隔离 |

### 技术栈

| 层级 | 技术 |
|------|------|
| 后端 | Python 3.12+, FastAPI, SQLAlchemy 2.0 (async), Pydantic v2 |
| 前端 | Vue 3, TypeScript, Vite, Lucide Icons |
| 数据库 | SQLite（开发）/ PostgreSQL（生产） |
| 认证 | JWT (PyJWT), HMAC Agent 签名, bcrypt |
| 实时通信 | WebSocket（按 Agent + 仪表盘双通道） |

### 快速开始

#### 环境要求

- Python 3.12+
- Node.js 18+（构建前端）

#### 1. 启动服务端

```bash
cd ops-platform/server
pip install -r requirements.txt
python app.py
```

首次启动时自动生成安全默认值（JWT 密钥、管理员密码、激活码）。
查看控制台输出获取生成的凭证。

#### 2. 启动 Agent

```bash
cd ops-platform/agent
pip install -r requirements.txt
python agent.py --server http://127.0.0.1:8000 --activation-code <你的激活码>
```

#### 3. 打开控制台

访问 `http://127.0.0.1:8000`，使用步骤 1 输出的凭证登录。

#### 4. 构建前端（可选）

```bash
cd ops-platform/frontend
npm install
npm run build
```

构建产物输出到 `server/static/`，由后端自动托管。

### 生产部署

启动前设置以下环境变量：

```bash
ENV=production
JWT_SECRET_KEY=<48位随机字符串>
DEFAULT_ADMIN_PASSWORD=<强密码>
DEFAULT_ACTIVATION_CODE=<自定义激活码>
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ops_platform
SERVER_PUBLIC_URL=https://ops.your-domain.com
CORS_ORIGINS=https://ops.your-domain.com
```

生产模式下如果未设置密钥，服务端**拒绝启动**。

### 安全加固

- JWT 密钥自动生成（开发）或强制设置（生产）— 无硬编码默认值
- Content-Security-Policy、X-Frame-Options、HSTS 安全头
- Webhook URL SSRF 防护（DNS 解析后校验内网地址）
- 远程命令白名单 + Shell 元字符过滤
- 文件操作路径遍历防护
- WebSocket 租户隔离（校验 Agent 归属）
- Agent 注册限速（每 IP 每分钟 5 次）
- 凭证文件已排除版本控制

### 项目结构

```
ops-platform/
├── agent/                  # 仅出站的监控 Agent
│   ├── agent.py            # Agent 核心（1480 行）
│   ├── remote/             # Shell、部署、文件下载执行器
│   └── stress/             # 压测运行器（HTTP、浏览器、基础设施）
├── server/                 # FastAPI 控制平面
│   ├── ops_platform/
│   │   ├── api/v1/routes/  # 16 个 API 路由模块
│   │   ├── core/           # 配置、安全、工具函数
│   │   ├── models.py       # 25 个 SQLAlchemy 模型
│   │   ├── scheduler.py    # 后台巡检与告警引擎
│   │   └── notifier.py     # 5 种通知渠道
│   └── requirements.txt
├── frontend/               # Vue 3 SPA
│   └── src/
│       ├── views/          # 18 个页面组件
│       ├── api.ts          # API 客户端（427 行）
│       └── router.ts       # 路由定义
└── scripts/                # 部署与打包脚本
```

### License

MIT
