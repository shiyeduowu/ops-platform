# -*- coding: utf-8 -*-
"""
Server 端巡检调度器

职责：
- 定时检查 Agent 心跳，发现失联主动告警
- 作为 Webhook Router，转发告警到通知渠道
- 持久化告警与转发记录

注意：
- 端口/磁盘/CPU/日志等高频检测由 Agent 本地执行
- Agent 仅在状态翻转时上报告警，避免告警风暴
- Server 巡检间隔可配置（默认 5 分钟）
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.db import AsyncSessionLocal
from ops_platform.models import Agent, AgentConfig, Alert, AlertForwardingLog, NotificationChannel, StressTest, StressTestTarget
from ops_platform.websocket import ws_manager

logger = logging.getLogger("ops-platform.scheduler")

# Server 巡检间隔（秒），可通过环境变量 PATROL_INTERVAL 覆盖
import os
PATROL_INTERVAL = int(os.environ.get("PATROL_INTERVAL", "300"))  # 默认 5 分钟


def _make_fingerprint(agent_id: str, alert_type: str, detail: str = "") -> str:
    """生成告警指纹，用于去重"""
    raw = f"{alert_type}:{agent_id}:{detail}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


async def create_alert_if_not_exists(
    db: AsyncSession,
    tenant_id: int,
    agent_id: str,
    alert_type: str,
    severity: str,
    message: str,
    fingerprint: str,
    details: dict | None = None,
) -> Alert | None:
    """
    创建告警（状态翻转去重）
    - 只在没有相同 fingerprint 的 open 告警时才创建
    - Agent 上报时也调用此函数，确保状态翻转才告警
    """
    existing = await db.execute(
        select(Alert).where(
            Alert.fingerprint == fingerprint,
            Alert.status == "open",
        )
    )
    if existing.scalar_one_or_none() is not None:
        return None

    alert = Alert(
        tenant_id=tenant_id,
        agent_id=agent_id,
        type=alert_type,
        severity=severity,
        message=message,
        status="open",
        details=details,
        fingerprint=fingerprint,
    )
    db.add(alert)
    await db.flush()
    return alert


async def resolve_alert(db: AsyncSession, fingerprint: str) -> None:
    """将指定 fingerprint 的 open 告警标记为 resolved"""
    result = await db.execute(
        select(Alert).where(
            Alert.fingerprint == fingerprint,
            Alert.status == "open",
        )
    )
    alert = result.scalar_one_or_none()
    if alert:
        alert.status = "resolved"


async def send_alert_notifications(
    db: AsyncSession,
    tenant_id: int,
    agent_id: str,
    agent_hostname: str,
    alert_type: str,
    severity: str,
    message: str,
    details: dict | None = None,
    alert_id: int | None = None,
) -> None:
    """
    Webhook Router: 将告警转发到所有启用的通知渠道，并持久化转发记录
    """
    try:
        from ops_platform.notifier import create_channel, format_alert_message

        result = await db.execute(
            select(NotificationChannel).where(
                NotificationChannel.tenant_id == tenant_id,
                NotificationChannel.enabled == True,
            )
        )
        channels = result.scalars().all()
        if not channels:
            return

        alert_data = {
            "type": alert_type,
            "severity": severity,
            "hostname": agent_hostname,
            "agent_id": agent_id,
            "message": message,
        }
        if details:
            alert_data["details"] = details

        title, content = format_alert_message(alert_data)

        for channel in channels:
            log_entry = AlertForwardingLog(
                tenant_id=tenant_id,
                alert_id=alert_id,
                channel_id=channel.id,
                channel_name=channel.name,
                channel_type=channel.channel_type,
            )
            try:
                notifier = create_channel(channel.channel_type, channel.config)
                if notifier:
                    ok = notifier.send(title, content,
                        alert_id=alert_id,
                        alert_type=alert_type,
                        severity=severity,
                        hostname=agent_hostname,
                        agent_id=agent_id,
                        message=message,
                        details=details,
                    )
                    if ok:
                        log_entry.status = "success"
                        logger.info(f"告警已转发: [{channel.name}] {alert_type}")
                    else:
                        log_entry.status = "failed"
                        log_entry.error_message = "通知发送失败"
                else:
                    log_entry.status = "failed"
                    log_entry.error_message = "不支持的通知渠道类型"
            except Exception as e:
                log_entry.status = "failed"
                log_entry.error_message = str(e)[:500]
                logger.error(f"通知转发失败 [{channel.name}]: {e}")
            db.add(log_entry)

        await db.flush()
    except Exception as e:
        logger.error(f"发送通知异常: {e}")


async def broadcast_alert_ws(alert: Alert) -> None:
    """WebSocket 广播告警"""
    try:
        from ops_platform.schemas import AlertRead
        await ws_manager.broadcast(
            alert.agent_id,
            {
                "event": "alert",
                "agent_id": alert.agent_id,
                "alert": AlertRead.model_validate(alert).model_dump(mode="json"),
            },
        )
    except Exception as e:
        logger.debug(f"WebSocket 广播失败: {e}")


async def notify_task_completion(
    db: AsyncSession,
    tenant_id: int,
    task_type: str,
    task_id: int,
    task_name: str,
    success: bool,
    detail: str = "",
) -> None:
    """
    任务完成通知（压力测试 / 远程命令 / 文件分发 / 软件部署）
    - 创建 Alert 记录
    - 通过通知渠道发送
    - 广播到前端 Dashboard WebSocket
    """
    severity = "info" if success else "warning"
    status_text = "执行完成" if success else "执行失败"
    type_label = {
        "stress_test": "压力测试",
        "remote_command": "远程命令",
        "file_distribution": "文件分发",
        "software_deployment": "软件部署",
    }.get(task_type, task_type)
    message = f"{type_label} [{task_name}] {status_text}"
    if detail:
        message += f"：{detail}"

    fp = _make_fingerprint(f"task:{task_id}", task_type)
    alert = await create_alert_if_not_exists(
        db=db,
        tenant_id=tenant_id,
        agent_id="system",
        alert_type=task_type,
        severity=severity,
        message=message,
        fingerprint=fp,
        details={"task_id": task_id, "task_name": task_name, "success": success},
    )
    if alert:
        await send_alert_notifications(
            db=db,
            tenant_id=tenant_id,
            agent_id="system",
            agent_hostname="Server",
            alert_type=task_type,
            severity=severity,
            message=message,
            alert_id=alert.id,
        )
        await db.commit()
        from ops_platform.schemas import AlertRead
        alert_data = AlertRead.model_validate(alert).model_dump(mode="json")
        await ws_manager.broadcast(
            f"_dashboard_{tenant_id}",
            {"event": "alert", "agent_id": "system", "alert": alert_data},
        )
    # 广播任务完成事件（无论是否创建了新 alert，都通知前端刷新）
    await ws_manager.broadcast(
        f"_dashboard_{tenant_id}",
        {
            "event": "task_completed",
            "task_type": task_type,
            "task_id": task_id,
            "success": success,
        },
    )


# ============================================================================
# 巡检函数 — Server 只负责心跳检测
# ============================================================================

async def check_agent_heartbeat(db: AsyncSession) -> None:
    """
    检查 Agent 心跳是否超时

    Agent 每 2 小时发送一次心跳作为存活证明。
    Server 巡检间隔可配置（默认 5 分钟）。
    超过 3 倍心跳间隔未响应 → 标记离线 + 告警。
    """
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(Agent).where(Agent.status == "online")
    )
    agents = list(result.scalars().all())
    if not agents:
        return

    # 批量获取所有在线 Agent 的配置，避免 N+1 查询
    agent_ids = [a.agent_id for a in agents]
    config_result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
    )
    configs_map: dict[str, AgentConfig] = {c.agent_id: c for c in config_result.scalars().all()}

    for agent in agents:
        if not agent.last_seen:
            continue

        config = configs_map.get(agent.agent_id)
        heartbeat_interval = 60  # 默认 60 秒
        if config and config.config_json:
            heartbeat_interval = config.config_json.get("heartbeat_interval_seconds", 60)

        # 兼容 naive datetime（SQLite）
        last_seen = agent.last_seen
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)

        # 超过 3 倍心跳间隔未响应 → 离线
        threshold = timedelta(seconds=heartbeat_interval * 3)
        if now - last_seen > threshold:
            agent.status = "offline"
            fp = _make_fingerprint(agent.agent_id, "agent_offline")
            alert = await create_alert_if_not_exists(
                db=db,
                tenant_id=agent.tenant_id,
                agent_id=agent.agent_id,
                alert_type="agent_offline",
                severity="critical",
                message=f"Agent {agent.hostname}({agent.agent_id}) 已失联，最后在线: {last_seen.strftime('%Y-%m-%d %H:%M:%S')}",
                fingerprint=fp,
                details={
                    "hostname": agent.hostname,
                    "ip": agent.ip,
                    "last_seen": last_seen.isoformat(),
                },
            )
            if alert:
                await send_alert_notifications(
                    db=db,
                    tenant_id=agent.tenant_id,
                    agent_id=agent.agent_id,
                    agent_hostname=agent.hostname,
                    alert_type="agent_offline",
                    severity="critical",
                    message=alert.message,
                    alert_id=alert.id,
                )
                await broadcast_alert_ws(alert)
                logger.warning(f"Agent 离线: {agent.hostname} ({agent.agent_id})")

    await db.commit()


async def check_scheduled_tests(db: AsyncSession) -> None:
    """检查到期的定时压测，自动触发执行"""
    now = datetime.now(timezone.utc)

    result = await db.execute(
        select(StressTest).where(
            StressTest.is_recurring == True,
            StressTest.next_run_at != None,
            StressTest.next_run_at <= now,
            StressTest.status.in_(["completed", "failed"]),
        )
    )
    tests = list(result.scalars().all())

    for test in tests:
        try:
            # 获取原始目标 Agent
            targets_result = await db.execute(
                select(StressTestTarget).where(StressTestTarget.test_id == test.id)
            )
            original_targets = list(targets_result.scalars().all())
            agent_ids = [t.agent_id for t in original_targets]

            if not agent_ids:
                logger.warning(f"定时测试 #{test.id} 无目标 Agent，跳过")
                continue

            # 创建新的测试实例（复制配置）
            new_test = StressTest(
                tenant_id=test.tenant_id,
                name=f"{test.name} (定时 {now.strftime('%m-%d %H:%M')})",
                test_type=test.test_type,
                config=test.config,
                status="pending",
                created_by=test.created_by,
            )
            db.add(new_test)
            await db.flush()

            for agent_id in agent_ids:
                db.add(StressTestTarget(test_id=new_test.id, agent_id=agent_id))

            # 更新下次执行时间
            if test.schedule_interval_seconds:
                test.next_run_at = now + timedelta(seconds=test.schedule_interval_seconds)
            else:
                # 没有间隔配置，停止循环
                test.is_recurring = False
                test.next_run_at = None

            await db.commit()
            logger.info(f"定时测试 #{test.id} 已触发，新测试 #{new_test.id}")

        except Exception as e:
            logger.error(f"定时测试 #{test.id} 触发失败: {e}", exc_info=True)


# ============================================================================
# 主循环
# ============================================================================

async def check_pending_knowledge_docs(db: AsyncSession) -> None:
    """处理待向量化的知识库文档"""
    try:
        from ops_platform.modules.aiops.rag.ingest import ingest_pending_documents

        count = await ingest_pending_documents(db)
        if count > 0:
            await db.commit()
    except ImportError:
        pass  # RAG 依赖未安装，跳过
    except Exception as e:
        logger.error(f"知识库摄入异常: {e}", exc_info=True)


async def patrol_loop() -> None:
    """
    Server 巡检主循环

    职责：定时检查 Agent 心跳是否超时
    间隔：PATROL_INTERVAL 秒（默认 300 秒 = 5 分钟）

    注意：端口/磁盘/CPU/日志检测由 Agent 本地高频执行，
         Server 只在收到 Agent 上报的告警时处理。
    """
    logger.info(f"Server 巡检调度器启动，间隔 {PATROL_INTERVAL} 秒")
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await check_agent_heartbeat(db)
                await check_scheduled_tests(db)
                await check_pending_knowledge_docs(db)
        except asyncio.CancelledError:
            logger.info("Server 巡检调度器已停止")
            break
        except Exception as e:
            logger.error(f"巡检异常: {e}", exc_info=True)

        await asyncio.sleep(PATROL_INTERVAL)
