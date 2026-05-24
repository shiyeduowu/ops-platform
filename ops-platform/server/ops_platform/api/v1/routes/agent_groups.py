from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ops_platform.api.deps import get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.db import get_db
from ops_platform.models import Agent, AgentGroup, AgentGroupMember
from ops_platform.schemas import (
    AgentGroupCreate,
    AgentGroupRead,
    AgentGroupUpdate,
    PaginatedResponse,
    UserContext,
)

router = APIRouter(prefix="/agent-groups", tags=["agent-groups"])


@router.post("", response_model=AgentGroupRead, status_code=201)
async def create_group(
    payload: AgentGroupCreate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    group = AgentGroup(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        description=payload.description,
        color=payload.color,
    )
    db.add(group)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "create", "agent_group", str(group.id))

    result = await db.execute(
        select(AgentGroup)
        .options(selectinload(AgentGroup.members))
        .where(AgentGroup.id == group.id)
    )
    return result.scalar_one()


@router.get("", response_model=PaginatedResponse[AgentGroupRead])
async def list_groups(
    search: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    base = select(AgentGroup).where(AgentGroup.tenant_id == current_user.tenant_id)
    if search:
        base = base.where(AgentGroup.name.ilike(f"%{search}%"))

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)

    result = await db.execute(
        base.options(selectinload(AgentGroup.members))
        .order_by(AgentGroup.created_at.desc())
        .offset(offset).limit(limit)
    )
    return {"items": result.scalars().all(), "total": total}


@router.get("/{group_id}", response_model=AgentGroupRead)
async def get_group(
    group_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentGroup)
        .options(selectinload(AgentGroup.members))
        .where(AgentGroup.id == group_id, AgentGroup.tenant_id == current_user.tenant_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")
    return group


@router.put("/{group_id}", response_model=AgentGroupRead)
async def update_group(
    group_id: int,
    payload: AgentGroupUpdate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentGroup)
        .where(AgentGroup.id == group_id, AgentGroup.tenant_id == current_user.tenant_id)
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")

    if payload.name is not None:
        group.name = payload.name
    if payload.description is not None:
        group.description = payload.description
    if payload.color is not None:
        group.color = payload.color

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "update", "agent_group", str(group_id))

    result = await db.execute(
        select(AgentGroup)
        .options(selectinload(AgentGroup.members))
        .where(AgentGroup.id == group.id)
    )
    return result.scalar_one()


@router.delete("/{group_id}", status_code=204)
async def delete_group(
    group_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentGroup).where(
            AgentGroup.id == group_id,
            AgentGroup.tenant_id == current_user.tenant_id,
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")

    await db.delete(group)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "delete", "agent_group", str(group_id))


@router.post("/{group_id}/members", response_model=AgentGroupRead, status_code=201)
async def add_members(
    group_id: int,
    agent_ids: list[str],
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AgentGroup).where(
            AgentGroup.id == group_id,
            AgentGroup.tenant_id == current_user.tenant_id,
        )
    )
    group = result.scalar_one_or_none()
    if group is None:
        raise HTTPException(status_code=404, detail="分组不存在")

    # 验证 Agent 存在且属于当前租户
    agents_result = await db.execute(
        select(Agent.agent_id).where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.agent_id.in_(agent_ids),
        )
    )
    valid_ids = {row[0] for row in agents_result.all()}
    invalid = set(agent_ids) - valid_ids
    if invalid:
        raise HTTPException(status_code=400, detail=f"Agent 不存在: {invalid}")

    # 获取已有成员
    existing_result = await db.execute(
        select(AgentGroupMember.agent_id).where(
            AgentGroupMember.group_id == group_id,
            AgentGroupMember.agent_id.in_(agent_ids),
        )
    )
    existing_ids = {row[0] for row in existing_result.all()}

    for aid in agent_ids:
        if aid not in existing_ids:
            db.add(AgentGroupMember(group_id=group_id, agent_id=aid))

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "add_members", "agent_group", str(group_id), details={"agent_ids": agent_ids})

    result = await db.execute(
        select(AgentGroup)
        .options(selectinload(AgentGroup.members))
        .where(AgentGroup.id == group_id)
    )
    return result.scalar_one()


@router.delete("/{group_id}/members/{agent_id}", status_code=204)
async def remove_member(
    group_id: int,
    agent_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # 验证分组属于当前租户
    group_result = await db.execute(
        select(AgentGroup).where(
            AgentGroup.id == group_id,
            AgentGroup.tenant_id == current_user.tenant_id,
        )
    )
    if group_result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="分组不存在")

    member_result = await db.execute(
        select(AgentGroupMember).where(
            AgentGroupMember.group_id == group_id,
            AgentGroupMember.agent_id == agent_id,
        )
    )
    member = member_result.scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="成员不存在")

    await db.delete(member)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "remove_member", "agent_group", str(group_id), details={"agent_id": agent_id})
