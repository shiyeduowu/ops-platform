"""主机相关工具"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.models import Agent, AgentGroup, AgentGroupMember
from ops_platform.modules.aiops.tools import tool


@tool(
    name="list_hosts",
    description="列出当前租户的所有主机（Agent），支持按状态筛选",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "按状态筛选: online, offline, warning（不传则返回全部）",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量上限，默认 50",
            },
        },
        "required": [],
    },
)
async def list_hosts(tenant_id: int, db: AsyncSession, status: str = None, limit: int = 50, **kw) -> dict:
    limit = min(max(1, int(limit)), 100)
    query = select(Agent).where(Agent.tenant_id == tenant_id)
    if status:
        query = query.where(Agent.status == status)
    query = query.order_by(Agent.last_seen.desc()).limit(limit)

    result = await db.execute(query)
    agents = result.scalars().all()

    return {
        "count": len(agents),
        "hosts": [
            {
                "agent_id": a.agent_id,
                "hostname": a.hostname,
                "ip": a.ip,
                "status": a.status,
                "version": a.version,
                "last_seen": a.last_seen.isoformat() if a.last_seen else None,
                "cpu": a.last_metrics.get("cpu_percent") if a.last_metrics else None,
                "memory": a.last_metrics.get("memory_percent") if a.last_metrics else None,
            }
            for a in agents
        ],
    }


@tool(
    name="get_host_detail",
    description="获取指定主机的详细信息，包括最近指标",
    parameters={
        "type": "object",
        "properties": {
            "agent_id": {
                "type": "string",
                "description": "主机的 Agent ID",
            },
        },
        "required": ["agent_id"],
    },
)
async def get_host_detail(tenant_id: int, db: AsyncSession, agent_id: str = "", **kw) -> dict:
    result = await db.execute(
        select(Agent).where(Agent.tenant_id == tenant_id, Agent.agent_id == agent_id)
    )
    agent = result.scalar_one_or_none()
    if not agent:
        return {"error": f"主机 {agent_id} 未找到"}

    # 只返回安全的指标字段
    safe_keys = {"cpu_percent", "memory_percent", "disk_percent", "memory_used", "memory_total", "disk_used", "disk_total"}
    filtered_metrics = {k: v for k, v in (agent.last_metrics or {}).items() if k in safe_keys}

    return {
        "agent_id": agent.agent_id,
        "hostname": agent.hostname,
        "ip": agent.ip,
        "status": agent.status,
        "version": agent.version,
        "last_seen": agent.last_seen.isoformat() if agent.last_seen else None,
        "last_metrics": filtered_metrics,
        "created_at": agent.created_at.isoformat(),
    }


@tool(
    name="get_host_groups",
    description="获取主机分组列表及成员",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_host_groups(tenant_id: int, db: AsyncSession, **kw) -> dict:
    result = await db.execute(
        select(AgentGroup).where(AgentGroup.tenant_id == tenant_id)
    )
    groups = result.scalars().all()

    group_data = []
    for g in groups:
        members_result = await db.execute(
            select(AgentGroupMember).where(AgentGroupMember.group_id == g.id)
        )
        members = members_result.scalars().all()
        group_data.append({
            "id": g.id,
            "name": g.name,
            "description": g.description,
            "member_count": len(members),
            "agent_ids": [m.agent_id for m in members],
        })

    return {"groups": group_data}
