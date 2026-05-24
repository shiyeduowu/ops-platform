"""告警相关工具"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.models import Alert
from ops_platform.modules.aiops.tools import tool


@tool(
    name="list_alerts",
    description="列出告警事件，支持按状态、严重级别、Agent 筛选",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "告警状态: open, acknowledged, resolved",
            },
            "severity": {
                "type": "string",
                "description": "严重级别: critical, warning, info",
            },
            "agent_id": {
                "type": "string",
                "description": "按 Agent ID 筛选",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量上限，默认 20",
            },
        },
        "required": [],
    },
)
async def list_alerts(
    tenant_id: int, db: AsyncSession,
    status: str = None, severity: str = None, agent_id: str = None, limit: int = 20,
    **kw,
) -> dict:
    limit = min(max(1, int(limit)), 100)
    query = select(Alert).where(Alert.tenant_id == tenant_id)
    if status:
        query = query.where(Alert.status == status)
    if severity:
        query = query.where(Alert.severity == severity)
    if agent_id:
        query = query.where(Alert.agent_id == agent_id)
    query = query.order_by(Alert.created_at.desc()).limit(limit)

    result = await db.execute(query)
    alerts = result.scalars().all()

    return {
        "count": len(alerts),
        "alerts": [
            {
                "id": a.id,
                "agent_id": a.agent_id,
                "type": a.type,
                "severity": a.severity,
                "message": a.message,
                "status": a.status,
                "created_at": a.created_at.isoformat(),
            }
            for a in alerts
        ],
    }


@tool(
    name="get_alert_stats",
    description="获取告警统计信息：按状态、严重级别分组计数",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_alert_stats(tenant_id: int, db: AsyncSession, **kw) -> dict:
    # 按状态统计
    status_q = (
        select(Alert.status, func.count().label("count"))
        .where(Alert.tenant_id == tenant_id)
        .group_by(Alert.status)
    )
    status_result = await db.execute(status_q)
    by_status = {row.status: row.count for row in status_result}

    # 按严重级别统计（仅 open 状态）
    severity_q = (
        select(Alert.severity, func.count().label("count"))
        .where(Alert.tenant_id == tenant_id, Alert.status == "open")
        .group_by(Alert.severity)
    )
    severity_result = await db.execute(severity_q)
    by_severity = {row.severity: row.count for row in severity_result}

    return {
        "by_status": by_status,
        "open_by_severity": by_severity,
        "total_open": by_status.get("open", 0),
    }


@tool(
    name="acknowledge_alert",
    description="确认一条告警（将状态从 open 改为 acknowledged）",
    parameters={
        "type": "object",
        "properties": {
            "alert_id": {
                "type": "integer",
                "description": "告警 ID",
            },
        },
        "required": ["alert_id"],
    },
)
async def acknowledge_alert(tenant_id: int, db: AsyncSession, alert_id: int = 0, **kw) -> dict:
    result = await db.execute(
        select(Alert).where(Alert.id == alert_id, Alert.tenant_id == tenant_id)
    )
    alert = result.scalar_one_or_none()
    if not alert:
        return {"error": f"告警 {alert_id} 未找到"}

    if alert.status != "open":
        return {"error": f"告警 {alert_id} 当前状态为 {alert.status}，无法确认"}

    alert.status = "acknowledged"
    await db.commit()

    return {"status": "ok", "message": f"告警 {alert_id} 已确认"}
