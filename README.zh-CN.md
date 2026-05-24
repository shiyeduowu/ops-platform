# Ops Platform — 中文文档

> 分布式运维监控与管理平台，Agent 仅出站通信，30 秒本地高频检测，状态翻转告警。

详细文档请参阅 [README.md](README.md#中文)。

## 快速开始

```bash
# 启动服务端
cd ops-platform/server
pip install -r requirements.txt
python app.py

# 启动 Agent（使用控制台输出的激活码）
cd ops-platform/agent
pip install -r requirements.txt
python agent.py --server http://127.0.0.1:8000 --activation-code <激活码>

# 打开控制台
# 浏览器访问 http://127.0.0.1:8000
```

## 功能清单

- Agent 监控（端口、磁盘、CPU、内存、Windows 服务、Java 进程、日志采集）
- 告警管理（5 种通知渠道：钉钉、企微、飞书、邮件、Webhook）
- 远程运维（Shell 命令、文件分发、软件部署）
- 压力测试（HTTP API、浏览器自动化、基础设施压测）
- 配置管理（设备影子模式、版本化拉取）
- 审计日志（全操作审计、租户隔离）

## 生产部署

```bash
ENV=production
JWT_SECRET_KEY=<48位随机字符串>
DEFAULT_ADMIN_PASSWORD=<强密码>
DEFAULT_ACTIVATION_CODE=<自定义激活码>
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/ops_platform
SERVER_PUBLIC_URL=https://ops.your-domain.com
CORS_ORIGINS=https://ops.your-domain.com
```
