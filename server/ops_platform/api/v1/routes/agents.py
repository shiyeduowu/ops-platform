from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.core.config import settings
from ops_platform.core.security import generate_agent_secret, stable_agent_id
from ops_platform.core.utils import next_version
from ops_platform.db import get_db
from ops_platform.models import ActivationCode, Agent, AgentConfig, License, Tenant, MetricHistory, StressTest, StressTestTarget, RemoteCommand, RemoteCommandTarget, FileDistribution, FileDistributionTarget, SoftwareDeployment, SoftwareDeploymentTarget
from ops_platform.schemas import (
    AgentAuthContext,
    AgentRead,
    AgentRegisterRequest,
    AgentRegisterResponse,
    DashboardSummary,
    FileDistributionItem,
    HeartbeatPayload,
    HeartbeatResponse,
    PaginatedResponse,
    RemoteCommandItem,
    SoftwareDeploymentItem,
    StressTestCommand,
    UpgradeInfo,
    UserContext,
)
from ops_platform.websocket import ws_manager


router = APIRouter(prefix="/agent", tags=["agent"])

# Agent 注册限速：每个 IP 每分钟最多 5 次注册尝试
_register_rate_limit: dict[str, list[float]] = {}
_REGISTER_RATE_WINDOW = 60.0
_REGISTER_RATE_MAX = 5


def _check_register_rate_limit(ip: str) -> None:
    now = time.time()
    attempts = _register_rate_limit.setdefault(ip, [])
    # 清理过期记录
    attempts[:] = [t for t in attempts if now - t < _REGISTER_RATE_WINDOW]
    if len(attempts) >= _REGISTER_RATE_MAX:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="注册请求过于频繁，请稍后再试")
    attempts.append(now)


def _ensure_aware(dt: datetime) -> datetime:
    """将 naive datetime 视为 UTC 并附加时区信息，避免 aware/naive 比较崩溃"""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


DEFAULT_AGENT_CONFIG: dict[str, Any] = {
    "port_checks": [],                  # Agent 本地端口检测列表
    "log_keywords": ["ERROR", "Exception", "FATAL"],  # 日志告警关键词
    "disk_threshold": 10,               # 磁盘剩余空间告警阈值 (%)
    "cpu_threshold": 90,                # CPU 使用率告警阈值 (%)
    "memory_threshold": 90,             # 内存使用率告警阈值 (%)
    "check_interval_seconds": 30,       # Agent 本地检测间隔（高频，30秒）
    "heartbeat_interval_seconds": 60,   # 心跳间隔（60秒，快速检测离线/恢复）
    "log_sources": [],                  # 日志采集源
    "browser_engine": "auto",           # 浏览器引擎: auto | chromedriver | playwright
    "chromedriver_path": "",            # ChromeDriver 路径（空=从 PATH 查找）
    "chrome_binary_path": "",           # Chrome 安装路径（可选）
    "service_catalog": [],              # 服务目录 [{service_key, name, product_line, owner, description}]
    "windows_services": [],             # Windows 服务名列表
    "log_discovery": [],                # 日志自动发现 [{root, mode, glob, service_key, id_prefix, scan_interval_seconds}]
    "stack_date_line_regex": r"^\d{4}-\d{2}-\d{2}",  # 堆栈日期行正则
    "max_concurrent_tails": 48,         # 最大并发 tail 数
    "log_cleanup_enabled": False,       # 启用日志清理
    "log_cleanup_retention_days": 30,   # 日志保留天数
    "log_cleanup_dry_run": True,        # 试运行模式
    "log_cleanup_interval_seconds": 3600,  # 清理间隔
}


async def _active_license_for_tenant(db: AsyncSession, tenant_id: int) -> License | None:
    result = await db.execute(
        select(License)
        .where(License.tenant_id == tenant_id)
        .order_by(License.id.desc())
    )
    license_row = result.scalars().first()
    if license_row is None:
        return None
    now = datetime.now(timezone.utc)
    if license_row.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="license inactive")
    if license_row.expire_at and _ensure_aware(license_row.expire_at) < now:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="license expired")
    return license_row


async def _assert_agent_capacity(db: AsyncSession, tenant_id: int, max_agents: int) -> None:
    result = await db.execute(select(func.count()).select_from(Agent).where(Agent.tenant_id == tenant_id))
    current_count = int(result.scalar() or 0)
    if current_count >= max_agents:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent quota exceeded")


@router.post("/register", response_model=AgentRegisterResponse, status_code=201)
async def register_agent(payload: AgentRegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    _check_register_rate_limit(client_ip)
    code_result = await db.execute(
        select(ActivationCode).where(ActivationCode.code == payload.activation_code)
    )
    activation = code_result.scalar_one_or_none()
    if activation is None or activation.status != "active":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid activation code")
    if activation.expire_at and _ensure_aware(activation.expire_at) < datetime.now(timezone.utc):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="activation code expired")
    if activation.used_count >= activation.max_uses:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="activation code exhausted")

    existing: Agent | None = None
    if payload.fingerprint:
        existing_result = await db.execute(
            select(Agent).where(
                Agent.tenant_id == activation.tenant_id,
                Agent.fingerprint == payload.fingerprint,
            )
        )
        existing = existing_result.scalar_one_or_none()

    if existing is not None:
        existing.hostname = payload.hostname
        existing.ip = payload.ip
        existing.version = payload.version
        existing.status = "online"
        existing.last_seen = datetime.now(timezone.utc)
        await db.commit()
        return AgentRegisterResponse(
            agent_id=existing.agent_id,
            secret=existing.secret_key,
            server_url=settings.server_public_url.rstrip("/"),
        )

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == activation.tenant_id))
    tenant = tenant_result.scalar_one()
    license_row = await _active_license_for_tenant(db, activation.tenant_id)
    await _assert_agent_capacity(
        db,
        activation.tenant_id,
        license_row.max_agents if license_row else tenant.max_agents,
    )

    agent_id = (
        stable_agent_id(f"{activation.tenant_id}:{payload.fingerprint}")
        if payload.fingerprint
        else uuid.uuid4().hex
    )
    agent = Agent(
        tenant_id=activation.tenant_id,
        agent_id=agent_id,
        hostname=payload.hostname,
        ip=payload.ip,
        status="online",
        last_seen=datetime.now(timezone.utc),
        secret_key=generate_agent_secret(),
        version=payload.version,
        fingerprint=payload.fingerprint,
    )
    db.add(agent)
    db.add(AgentConfig(agent_id=agent_id, config_json=dict(DEFAULT_AGENT_CONFIG), config_version="v1"))
    activation.used_count += 1
    await db.commit()
    await log_audit(db, agent.tenant_id, 0, "system", "register_agent", "agent", agent.agent_id)

    return AgentRegisterResponse(
        agent_id=agent.agent_id,
        secret=agent.secret_key,
        server_url=settings.server_public_url.rstrip("/"),
    )


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def heartbeat(
    payload: HeartbeatPayload,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    if payload.agent_id != agent_context.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent id mismatch")

    await _active_license_for_tenant(db, agent_context.tenant_id)

    result = await db.execute(select(Agent).where(Agent.agent_id == agent_context.agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    config_result = await db.execute(select(AgentConfig).where(AgentConfig.agent_id == agent.agent_id))
    config = config_result.scalar_one_or_none()
    if config is None:
        config = AgentConfig(
            agent_id=agent.agent_id,
            config_json=dict(DEFAULT_AGENT_CONFIG),
            config_version="v1",
        )
        db.add(config)

    agent.status = "online"
    agent.last_seen = datetime.now(timezone.utc)
    agent.last_metrics = payload.metrics
    if payload.hostname:
        agent.hostname = payload.hostname
    if payload.ip:
        agent.ip = payload.ip
    if payload.version:
        agent.version = payload.version

    # Agent 恢复在线 → 自动解决离线告警 + 发送恢复通知
    from ops_platform.scheduler import _make_fingerprint, resolve_alert, create_alert_if_not_exists, send_alert_notifications, broadcast_alert_ws
    offline_fp = _make_fingerprint(agent.agent_id, "agent_offline")
    was_offline = agent.status == "offline"
    await resolve_alert(db, offline_fp)

    # 发送恢复通知
    if was_offline:
        recovery_fp = _make_fingerprint(agent.agent_id, "agent_recovered")
        recovery_alert = await create_alert_if_not_exists(
            db=db,
            tenant_id=agent.tenant_id,
            agent_id=agent.agent_id,
            alert_type="agent_recovered",
            severity="info",
            message=f"Agent {agent.hostname}({agent.agent_id}) 已恢复在线",
            fingerprint=recovery_fp,
            details={"hostname": agent.hostname, "ip": agent.ip},
        )
        if recovery_alert:
            await send_alert_notifications(
                db=db,
                tenant_id=agent.tenant_id,
                agent_id=agent.agent_id,
                agent_hostname=agent.hostname,
                alert_type="agent_recovered",
                severity="info",
                message=recovery_alert.message,
                alert_id=recovery_alert.id,
            )
            await broadcast_alert_ws(recovery_alert)

    # 存储指标历史
    if payload.metrics:
        metric_record = MetricHistory(
            agent_id=agent.agent_id,
            tenant_id=agent.tenant_id,
            metrics=payload.metrics,
        )
        db.add(metric_record)

    # 处理 Agent 上报的端口检测结果
    if payload.metrics and payload.metrics.get("port_check_results"):
        from ops_platform.scheduler import create_alert_if_not_exists, send_alert_notifications, broadcast_alert_ws, _make_fingerprint, resolve_alert
        for pr in payload.metrics["port_check_results"]:
            port = pr.get("port")
            port_status = pr.get("status", "unknown")
            if port_status == "closed" and port:
                fp = _make_fingerprint(agent.agent_id, "port_down", str(port))
                alert = await create_alert_if_not_exists(
                    db=db,
                    tenant_id=agent.tenant_id,
                    agent_id=agent.agent_id,
                    alert_type="port_down",
                    severity="critical",
                    message=f"Agent {agent.hostname} 端口 {port} 不可达",
                    fingerprint=fp,
                    details={"hostname": agent.hostname, "port": port},
                )
                if alert:
                    await send_alert_notifications(
                        db=db,
                        tenant_id=agent.tenant_id,
                        agent_id=agent.agent_id,
                        agent_hostname=agent.hostname,
                        alert_type="port_down",
                        severity="critical",
                        message=alert.message,
                    )
                    await broadcast_alert_ws(alert)
            elif port_status == "open" and port:
                await resolve_alert(db, _make_fingerprint(agent.agent_id, "port_down", str(port)))

    # 处理 Windows 服务状态
    if payload.metrics and payload.metrics.get("windows_services"):
        from ops_platform.scheduler import create_alert_if_not_exists, send_alert_notifications, broadcast_alert_ws, _make_fingerprint, resolve_alert
        for svc_name, is_running in payload.metrics["windows_services"].items():
            if not is_running:
                fp = _make_fingerprint(agent.agent_id, "service_down", str(svc_name))
                alert = await create_alert_if_not_exists(
                    db=db,
                    tenant_id=agent.tenant_id,
                    agent_id=agent.agent_id,
                    alert_type="service_down",
                    severity="critical",
                    message=f"Agent {agent.hostname} Windows 服务 {svc_name} 未运行",
                    fingerprint=fp,
                    details={"hostname": agent.hostname, "service_name": svc_name},
                )
                if alert:
                    await send_alert_notifications(
                        db=db, tenant_id=agent.tenant_id, agent_id=agent.agent_id,
                        agent_hostname=agent.hostname, alert_type="service_down",
                        severity="critical", message=alert.message,
                    )
                    await broadcast_alert_ws(alert)
            else:
                await resolve_alert(db, _make_fingerprint(agent.agent_id, "service_down", str(svc_name)))

    # 处理 Java 进程状态
    if payload.metrics and payload.metrics.get("java_processes"):
        from ops_platform.scheduler import create_alert_if_not_exists, send_alert_notifications, broadcast_alert_ws, _make_fingerprint, resolve_alert
        for sk, is_running in payload.metrics["java_processes"].items():
            if not is_running:
                fp = _make_fingerprint(agent.agent_id, "java_process_down", str(sk))
                alert = await create_alert_if_not_exists(
                    db=db,
                    tenant_id=agent.tenant_id,
                    agent_id=agent.agent_id,
                    alert_type="java_process_down",
                    severity="critical",
                    message=f"Agent {agent.hostname} Java 进程 {sk} 未找到",
                    fingerprint=fp,
                    details={"hostname": agent.hostname, "service_key": sk},
                )
                if alert:
                    await send_alert_notifications(
                        db=db, tenant_id=agent.tenant_id, agent_id=agent.agent_id,
                        agent_hostname=agent.hostname, alert_type="java_process_down",
                        severity="critical", message=alert.message,
                    )
                    await broadcast_alert_ws(alert)
            else:
                await resolve_alert(db, _make_fingerprint(agent.agent_id, "java_process_down", str(sk)))

    await db.commit()

    config_changed = config.config_version != payload.config_version
    need_upgrade = bool(
        payload.version
        and settings.agent_upgrade_url
        and payload.version != settings.agent_target_version
    )

    # 查询待下发的压测命令
    commands: list[StressTestCommand] = []
    pending_targets_result = await db.execute(
        select(StressTestTarget)
        .join(StressTest)
        .where(
            StressTestTarget.agent_id == agent.agent_id,
            StressTestTarget.status == "pending",
            StressTest.status.in_(["pending", "running"]),
        )
    )
    for target in pending_targets_result.scalars().all():
        # 通过 relationship 加载 test
        test_result = await db.execute(
            select(StressTest).where(StressTest.id == target.test_id)
        )
        test = test_result.scalar_one_or_none()
        if test:
            commands.append(StressTestCommand(
                command_id=f"stress:{test.id}:{target.id}",
                test_id=test.id,
                test_type=test.test_type,
                config=test.config,
                action="start",
            ))
            target.status = "running"
            target.command_acked = True
            test.status = "running"

    if commands:
        await db.commit()

    # 查询待下发的远程命令
    remote_commands: list[RemoteCommandItem] = []
    pending_rc_targets_result = await db.execute(
        select(RemoteCommandTarget)
        .join(RemoteCommand)
        .where(
            RemoteCommandTarget.agent_id == agent.agent_id,
            RemoteCommandTarget.status == "pending",
            RemoteCommand.status.in_(["pending", "running"]),
        )
    )
    for rc_target in pending_rc_targets_result.scalars().all():
        rc_result = await db.execute(
            select(RemoteCommand).where(RemoteCommand.id == rc_target.command_id)
        )
        rc = rc_result.scalar_one_or_none()
        if rc:
            remote_commands.append(RemoteCommandItem(
                command_id=rc.id,
                command_type=rc.command_type,
                command_text=rc.command_text,
                timeout_seconds=rc.timeout_seconds,
            ))
            rc_target.status = "running"
            rc.status = "running"

    if remote_commands:
        await db.commit()

    # 查询待下发的文件分发
    file_distributions: list[FileDistributionItem] = []
    pending_fd_targets_result = await db.execute(
        select(FileDistributionTarget)
        .join(FileDistribution)
        .where(
            FileDistributionTarget.agent_id == agent.agent_id,
            FileDistributionTarget.status == "pending",
            FileDistribution.status.in_(["pending", "running"]),
        )
    )
    for fd_target in pending_fd_targets_result.scalars().all():
        fd_result = await db.execute(
            select(FileDistribution).where(FileDistribution.id == fd_target.distribution_id)
        )
        fd = fd_result.scalar_one_or_none()
        if fd:
            from ops_platform.api.v1.routes.file_distributions import _generate_download_token
            token = _generate_download_token(fd.id)
            file_distributions.append(FileDistributionItem(
                distribution_id=fd.id,
                filename=fd.filename,
                target_path=fd.target_path,
                file_size=fd.file_size,
                checksum_md5=fd.checksum_md5,
                download_token=token,
            ))
            fd_target.status = "downloading"
            fd.status = "running"

    if file_distributions:
        await db.commit()

    # 查询待下发的软件部署
    software_deployments: list[SoftwareDeploymentItem] = []
    pending_sd_targets_result = await db.execute(
        select(SoftwareDeploymentTarget)
        .join(SoftwareDeployment)
        .where(
            SoftwareDeploymentTarget.agent_id == agent.agent_id,
            SoftwareDeploymentTarget.file_status == "pending",
            SoftwareDeployment.status.in_(["pending", "running"]),
        )
    )
    for sd_target in pending_sd_targets_result.scalars().all():
        sd_result = await db.execute(
            select(SoftwareDeployment).where(SoftwareDeployment.id == sd_target.deployment_id)
        )
        sd = sd_result.scalar_one_or_none()
        if sd:
            from ops_platform.api.v1.routes.deployments import _generate_download_token as _sd_token
            token = _sd_token(sd.id)
            software_deployments.append(SoftwareDeploymentItem(
                deployment_id=sd.id,
                installer_filename=sd.installer_filename,
                install_command=sd.install_command,
                install_args=sd.install_args,
                timeout_seconds=sd.timeout_seconds,
                download_token=token,
            ))
            sd_target.file_status = "downloading"
            sd.status = "running"

    if software_deployments:
        await db.commit()

    response = HeartbeatResponse(
        config_changed=config_changed,
        config=config.config_json if config_changed else {},
        config_version=config.config_version,
        upgrade=UpgradeInfo(
            need_upgrade=need_upgrade,
            version=settings.agent_target_version if need_upgrade else None,
            upgrade_url=settings.agent_upgrade_url if need_upgrade else None,
        ),
        server_time=int(time.time()),
        commands=commands,
        remote_commands=remote_commands,
        file_distributions=file_distributions,
        software_deployments=software_deployments,
    )

    await ws_manager.broadcast(
        agent.agent_id,
        {
            "event": "metrics",
            "agent_id": agent.agent_id,
            "metrics": payload.metrics,
            "config_version": config.config_version,
            "server_time": response.server_time,
        },
    )
    return response


@router.get("/list", response_model=PaginatedResponse[AgentRead])
async def list_agents(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    search: str | None = Query(default=None),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(Agent).where(Agent.tenant_id == current_user.tenant_id)
    if search:
        like = f"%{search}%"
        base = base.where(
            (Agent.hostname.ilike(like)) | (Agent.agent_id.ilike(like)) | (Agent.ip.ilike(like))
        )
    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)
    result = await db.execute(base.order_by(Agent.created_at.desc()).offset(offset).limit(limit))
    return {"items": result.scalars().all(), "total": total}


@router.get("/{agent_id}", response_model=AgentRead)
async def get_agent(
    agent_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.agent_id == agent_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from ops_platform.models import Alert
    from ops_platform.schemas import AlertRead

    agents_result = await db.execute(
        select(Agent).where(Agent.tenant_id == current_user.tenant_id)
    )
    agents = list(agents_result.scalars().all())
    alerts_result = await db.execute(
        select(Alert)
        .where(Alert.tenant_id == current_user.tenant_id)
        .order_by(Alert.created_at.desc())
        .limit(20)
    )
    recent_alerts = list(alerts_result.scalars().all())
    open_count_result = await db.execute(
        select(func.count()).select_from(Alert).where(
            Alert.tenant_id == current_user.tenant_id,
            Alert.status == "open",
        )
    )
    open_count = int(open_count_result.scalar() or 0)
    return DashboardSummary(
        total_agents=len(agents),
        online_agents=sum(1 for item in agents if item.status == "online"),
        offline_agents=sum(1 for item in agents if item.status != "online"),
        open_alerts=open_count,
        recent_alerts=[AlertRead.model_validate(item) for item in recent_alerts],
        agent_list=agents,
    )


@router.get("/{agent_id}/metrics")
async def get_agent_metrics(
    agent_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=1000),
    hours: int = Query(default=24, ge=1, le=168),
):
    """获取Agent指标历史"""
    # 验证权限
    result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.agent_id == agent_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    # 查询指标历史
    from datetime import timedelta
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    metrics_result = await db.execute(
        select(MetricHistory)
        .where(
            MetricHistory.agent_id == agent_id,
            MetricHistory.recorded_at >= since,
        )
        .order_by(MetricHistory.recorded_at.desc())
        .limit(limit)
    )
    metrics = metrics_result.scalars().all()

    return {
        "agent_id": agent_id,
        "metrics": [
            {
                "recorded_at": m.recorded_at.isoformat(),
                "data": m.metrics,
            }
            for m in metrics
        ],
    }
