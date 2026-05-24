"""脚本与远程命令相关工具"""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.models import RemoteCommand, RemoteCommandTarget
from ops_platform.modules.aiops.tools import tool


@tool(
    name="list_scripts",
    description="列出远程命令/脚本列表",
    parameters={
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "description": "按状态筛选: draft, running, finished",
            },
            "limit": {
                "type": "integer",
                "description": "返回数量上限，默认 20",
            },
        },
        "required": [],
    },
)
async def list_scripts(
    tenant_id: int, db: AsyncSession, status: str = None, limit: int = 20, **kw,
) -> dict:
    limit = min(max(1, int(limit)), 100)
    query = select(RemoteCommand).where(RemoteCommand.tenant_id == tenant_id)
    if status:
        query = query.where(RemoteCommand.status == status)
    query = query.order_by(RemoteCommand.created_at.desc()).limit(limit)

    result = await db.execute(query)
    commands = result.scalars().all()

    return {
        "count": len(commands),
        "scripts": [
            {
                "id": c.id,
                "name": c.name,
                "command_type": c.command_type,
                "status": c.status,
                "created_by": c.created_by,
                "created_at": c.created_at.isoformat(),
            }
            for c in commands
        ],
    }


@tool(
    name="get_script_result",
    description="获取指定命令的执行结果（每个 Agent 的 stdout/stderr/exit_code）",
    parameters={
        "type": "object",
        "properties": {
            "command_id": {
                "type": "integer",
                "description": "命令 ID",
            },
        },
        "required": ["command_id"],
    },
)
async def get_script_result(tenant_id: int, db: AsyncSession, command_id: int = 0, **kw) -> dict:
    # 验证命令属于该租户
    cmd_result = await db.execute(
        select(RemoteCommand).where(RemoteCommand.id == command_id, RemoteCommand.tenant_id == tenant_id)
    )
    cmd = cmd_result.scalar_one_or_none()
    if not cmd:
        return {"error": f"命令 {command_id} 未找到"}

    targets_result = await db.execute(
        select(RemoteCommandTarget).where(RemoteCommandTarget.command_id == command_id)
    )
    targets = targets_result.scalars().all()

    return {
        "command_id": cmd.id,
        "name": cmd.name,
        "status": cmd.status,
        "results": [
            {
                "agent_id": t.agent_id,
                "status": t.status,
                "exit_code": t.exit_code,
                "stdout": (t.stdout or "")[:2000],  # 截断过长输出
                "stderr": (t.stderr or "")[:1000],
            }
            for t in targets
        ],
    }
