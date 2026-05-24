"""系统概览与部署相关工具"""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.models import (
    Agent,
    Alert,
    FileDistribution,
    SoftwareDeployment,
    Tenant,
    User,
)
from ops_platform.modules.aiops.tools import tool


@tool(
    name="get_system_overview",
    description="获取系统总览：主机数量、告警数量、用户数量等关键指标",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_system_overview(tenant_id: int, db: AsyncSession, **kw) -> dict:
    # 主机统计
    agent_total = await db.execute(select(func.count()).where(Agent.tenant_id == tenant_id))
    agent_online = await db.execute(
        select(func.count()).where(Agent.tenant_id == tenant_id, Agent.status == "online")
    )

    # 告警统计
    alerts_open = await db.execute(
        select(func.count()).where(Alert.tenant_id == tenant_id, Alert.status == "open")
    )
    alerts_critical = await db.execute(
        select(func.count()).where(
            Alert.tenant_id == tenant_id, Alert.status == "open", Alert.severity == "critical"
        )
    )

    # 用户统计
    user_count = await db.execute(select(func.count()).where(User.tenant_id == tenant_id))

    return {
        "hosts": {
            "total": int(agent_total.scalar() or 0),
            "online": int(agent_online.scalar() or 0),
        },
        "alerts": {
            "open": int(alerts_open.scalar() or 0),
            "critical": int(alerts_critical.scalar() or 0),
        },
        "users": int(user_count.scalar() or 0),
    }


@tool(
    name="list_deployments",
    description="列出软件部署任务",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "按状态筛选: draft, deploying, finished, failed",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量上限，默认 10",
            },
        },
        "required": [],
    },
)
async def list_deployments(
    tenant_id: int, db: AsyncSession, status: str = None, limit: int = 10, **kw,
) -> dict:
    limit = min(max(1, int(limit)), 50)
    query = select(SoftwareDeployment).where(SoftwareDeployment.tenant_id == tenant_id)
    if status:
        query = query.where(SoftwareDeployment.status == status)
    query = query.order_by(SoftwareDeployment.created_at.desc()).limit(limit)

    result = await db.execute(query)
    deps = result.scalars().all()

    return {
        "count": len(deps),
        "deployments": [
            {
                "id": d.id,
                "name": d.name,
                "software_name": d.software_name,
                "version": d.version,
                "status": d.status,
                "created_at": d.created_at.isoformat(),
            }
            for d in deps
        ],
    }


@tool(
    name="list_distributions",
    description="列出文件分发任务",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "按状态筛选: draft, distributing, finished, failed",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量上限，默认 10",
            },
        },
        "required": [],
    },
)
async def list_distributions(
    tenant_id: int, db: AsyncSession, status: str = None, limit: int = 10, **kw,
) -> dict:
    limit = min(max(1, int(limit)), 50)
    query = select(FileDistribution).where(FileDistribution.tenant_id == tenant_id)
    if status:
        query = query.where(FileDistribution.status == status)
    query = query.order_by(FileDistribution.created_at.desc()).limit(limit)

    result = await db.execute(query)
    dists = result.scalars().all()

    return {
        "count": len(dists),
        "distributions": [
            {
                "id": d.id,
                "name": d.name,
                "filename": d.filename,
                "status": d.status,
                "created_at": d.created_at.isoformat(),
            }
            for d in dists
        ],
    }
