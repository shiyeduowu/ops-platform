from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select, func, or_
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.db import get_db
from ops_platform.models import Agent, Log
from ops_platform.schemas import AgentAuthContext, LogCreate, LogRead, UserContext
from ops_platform.websocket import ws_manager


def _escape_like(value: str) -> str:
    """转义 LIKE 通配符，防止 % 和 _ 被当作模式匹配"""
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


router = APIRouter(prefix="/logs", tags=["日志管理"])


def _fingerprint(payload: LogCreate) -> str:
    if payload.fingerprint:
        return payload.fingerprint
    raw = f"{payload.agent_id}:{payload.service_key}:{payload.content[:500]}"
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


@router.get("", response_model=list[LogRead])
async def list_logs(
    agent_id: str | None = None,
    service_key: str | None = None,
    keyword: str | None = Query(None, max_length=200, description="关键词搜索"),
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    查询日志列表

    支持过滤：
    - agent_id: Agent ID
    - service_key: 服务标识
    - keyword: 关键词搜索（模糊匹配内容）
    - start_time/end_time: 时间范围
    """
    query = (
        select(Log)
        .join(Agent, Agent.agent_id == Log.agent_id)
        .where(Agent.tenant_id == current_user.tenant_id)
    )

    if agent_id:
        query = query.where(Log.agent_id == agent_id)
    if service_key:
        query = query.where(Log.service_key == service_key)
    if keyword:
        query = query.where(Log.content.ilike(f"%{_escape_like(keyword)}%", escape="\\"))
    if start_time:
        query = query.where(Log.created_at >= start_time)
    if end_time:
        query = query.where(Log.created_at <= end_time)

    result = await db.execute(
        query.order_by(Log.created_at.desc()).limit(limit).offset(offset)
    )
    return result.scalars().all()


@router.get("/search")
async def search_logs(
    keyword: str = Query(..., min_length=1, max_length=200, description="搜索关键词"),
    agent_id: str | None = None,
    service_key: str | None = None,
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    全文搜索日志

    返回匹配的日志条目，高亮显示匹配内容
    """
    query = (
        select(Log)
        .join(Agent, Agent.agent_id == Log.agent_id)
        .where(Agent.tenant_id == current_user.tenant_id)
    )

    if agent_id:
        query = query.where(Log.agent_id == agent_id)
    if service_key:
        query = query.where(Log.service_key == service_key)
    if keyword:
        query = query.where(Log.content.ilike(f"%{_escape_like(keyword)}%", escape="\\"))
    if start_time:
        query = query.where(Log.created_at >= start_time)
    if end_time:
        query = query.where(Log.created_at <= end_time)

    # 统计匹配总数（与主查询保持相同的过滤条件）
    count_query = (
        select(func.count())
        .select_from(Log)
        .join(Agent, Agent.agent_id == Log.agent_id)
        .where(Agent.tenant_id == current_user.tenant_id)
    )
    if agent_id:
        count_query = count_query.where(Log.agent_id == agent_id)
    if service_key:
        count_query = count_query.where(Log.service_key == service_key)
    if keyword:
        count_query = count_query.where(Log.content.ilike(f"%{_escape_like(keyword)}%", escape="\\"))
    if start_time:
        count_query = count_query.where(Log.created_at >= start_time)
    if end_time:
        count_query = count_query.where(Log.created_at <= end_time)

    total_result = await db.execute(count_query)
    total = int(total_result.scalar() or 0)

    result = await db.execute(
        query.order_by(Log.created_at.desc()).limit(limit)
    )
    logs = result.scalars().all()

    # 高亮匹配内容
    highlighted = []
    for log in logs:
        content = log.content
        if keyword:
            # 简单高亮（实际可以用更复杂的高亮逻辑）
            content = content.replace(
                keyword, f"**{keyword}**"
            ) if keyword.lower() in content.lower() else content

        highlighted.append({
            "id": log.id,
            "agent_id": log.agent_id,
            "service_key": log.service_key,
            "content": log.content,
            "highlighted_content": content,
            "fingerprint": log.fingerprint,
            "created_at": log.created_at.isoformat() if log.created_at else None,
        })

    return {
        "total": total,
        "keyword": keyword,
        "logs": highlighted,
    }


@router.get("/stats")
async def get_log_stats(
    hours: int = Query(default=24, ge=1, le=168),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取日志统计信息"""
    from datetime import timedelta

    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    # 总数
    total_result = await db.execute(
        select(func.count())
        .select_from(Log)
        .join(Agent, Agent.agent_id == Log.agent_id)
        .where(
            Agent.tenant_id == current_user.tenant_id,
            Log.created_at >= since,
        )
    )
    total = int(total_result.scalar() or 0)

    # 按服务统计
    service_result = await db.execute(
        select(Log.service_key, func.count())
        .join(Agent, Agent.agent_id == Log.agent_id)
        .where(
            Agent.tenant_id == current_user.tenant_id,
            Log.created_at >= since,
        )
        .group_by(Log.service_key)
    )
    by_service = {row[0]: row[1] for row in service_result.all()}

    # 按Agent统计
    agent_result = await db.execute(
        select(Log.agent_id, func.count())
        .join(Agent, Agent.agent_id == Log.agent_id)
        .where(
            Agent.tenant_id == current_user.tenant_id,
            Log.created_at >= since,
        )
        .group_by(Log.agent_id)
        .order_by(func.count().desc())
        .limit(10)
    )
    by_agent = {row[0]: row[1] for row in agent_result.all()}

    return {
        "total": total,
        "hours": hours,
        "by_service": by_service,
        "top_agents": by_agent,
    }


@router.post("", response_model=LogRead, status_code=201)
async def create_log(
    payload: LogCreate,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    if payload.agent_id != agent_context.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent id mismatch")
    result = await db.execute(select(Agent).where(Agent.agent_id == payload.agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    log = Log(
        agent_id=payload.agent_id,
        service_key=payload.service_key,
        content=payload.content,
        fingerprint=_fingerprint(payload),
    )
    db.add(log)
    await db.commit()
    await db.refresh(log)

    await ws_manager.broadcast(
        log.agent_id,
        {
            "event": "log",
            "agent_id": log.agent_id,
            "log": LogRead.model_validate(log).model_dump(mode="json"),
        },
    )
    return log
