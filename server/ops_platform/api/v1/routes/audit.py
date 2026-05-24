# -*- coding: utf-8 -*-
"""
审计日志 API
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.db import get_db
from ops_platform.models import AuditLog
from ops_platform.schemas import UserContext


router = APIRouter(prefix="/audit", tags=["审计日志"])


# ============================================================================
# 响应模型
# ============================================================================

class AuditLogRead(BaseModel):
    id: int
    user_id: int
    username: str
    action: str
    resource_type: str
    resource_id: Optional[str] = None
    details: Optional[dict] = None
    ip_address: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True


class AuditLogStats(BaseModel):
    total: int
    today: int
    by_action: dict[str, int]
    by_resource: dict[str, int]


# ============================================================================
# API 路由
# ============================================================================

@router.get("/", response_model=list[AuditLogRead])
async def list_audit_logs(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    action: Optional[str] = Query(None, description="操作类型过滤"),
    resource_type: Optional[str] = Query(None, description="资源类型过滤"),
    user_id: Optional[int] = Query(None, description="用户ID过滤"),
    start_time: Optional[datetime] = Query(None, description="开始时间"),
    end_time: Optional[datetime] = Query(None, description="结束时间"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """获取审计日志列表"""
    query = select(AuditLog).where(AuditLog.tenant_id == current_user.tenant_id)

    if action:
        query = query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
    if start_time:
        query = query.where(AuditLog.created_at >= start_time)
    if end_time:
        query = query.where(AuditLog.created_at <= end_time)

    query = query.order_by(AuditLog.created_at.desc()).limit(limit).offset(offset)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/stats", response_model=AuditLogStats)
async def get_audit_stats(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取审计日志统计"""
    # 总数
    total_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.tenant_id == current_user.tenant_id
        )
    )
    total = int(total_result.scalar() or 0)

    # 今日
    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_result = await db.execute(
        select(func.count()).select_from(AuditLog).where(
            AuditLog.tenant_id == current_user.tenant_id,
            AuditLog.created_at >= today_start,
        )
    )
    today = int(today_result.scalar() or 0)

    # 按操作类型统计
    action_result = await db.execute(
        select(AuditLog.action, func.count())
        .where(AuditLog.tenant_id == current_user.tenant_id)
        .group_by(AuditLog.action)
    )
    by_action = {row[0]: row[1] for row in action_result.all()}

    # 按资源类型统计
    resource_result = await db.execute(
        select(AuditLog.resource_type, func.count())
        .where(AuditLog.tenant_id == current_user.tenant_id)
        .group_by(AuditLog.resource_type)
    )
    by_resource = {row[0]: row[1] for row in resource_result.all()}

    return AuditLogStats(
        total=total,
        today=today,
        by_action=by_action,
        by_resource=by_resource,
    )


# ============================================================================
# 辅助函数（供其他模块调用）
# ============================================================================

async def log_audit(
    db: AsyncSession,
    tenant_id: int,
    user_id: int,
    username: str,
    action: str,
    resource_type: str,
    resource_id: str = None,
    details: dict = None,
    ip_address: str = None,
):
    """
    记录审计日志

    Args:
        db: 数据库会话
        tenant_id: 租户ID
        user_id: 用户ID
        username: 用户名
        action: 操作类型 (login/create/update/delete)
        resource_type: 资源类型 (agent/config/alert/channel/user)
        resource_id: 资源ID
        details: 详细信息
        ip_address: IP地址
    """
    log = AuditLog(
        tenant_id=tenant_id,
        user_id=user_id,
        username=username,
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id else None,
        details=details,
        ip_address=ip_address,
    )
    db.add(log)
    # 不在这里 commit，由调用方决定何时提交
