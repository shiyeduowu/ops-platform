"""指标查询工具"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.models import MetricHistory
from ops_platform.modules.aiops.tools import tool


@tool(
    name="query_metrics",
    description="查询指定主机的历史指标数据（CPU、内存、磁盘等时序数据）",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "主机 Agent ID",
            },
            "limit": {
                "type": "integer",
                "description": "返回最近 N 条记录，默认 10",
            },
        },
        "required": ["agent_id"],
    },
)
async def query_metrics(tenant_id: int, db: AsyncSession, agent_id: str = "", limit: int = 10, **kw) -> dict:
    limit = min(max(1, int(limit)), 50)
    result = await db.execute(
        select(MetricHistory)
        .where(MetricHistory.tenant_id == tenant_id, MetricHistory.agent_id == agent_id)
        .order_by(MetricHistory.recorded_at.desc())
        .limit(limit)
    )
    records = result.scalars().all()

    return {
        "agent_id": agent_id,
        "record_count": len(records),
        "metrics": [
            {
                "recorded_at": r.recorded_at.isoformat(),
                "data": r.metrics,
            }
            for r in records
        ],
    }


@tool(
    name="get_latest_metrics",
    description="获取所有在线主机的最新指标快照（CPU、内存、磁盘）",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_latest_metrics(tenant_id: int, db: AsyncSession, **kw) -> dict:
    from ops_platform.models import Agent

    result = await db.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.status == "online")
    )
    agents = result.scalars().all()

    return {
        "online_count": len(agents),
        "hosts": [
            {
                "agent_id": a.agent_id,
                "hostname": a.hostname,
                "metrics": a.last_metrics,
            }
            for a in agents
        ],
    }
