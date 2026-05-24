from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.db import get_db
from ops_platform.models import Alert, Agent
from ops_platform.schemas import AgentAuthContext, AlertCreate, AlertRead, UserContext
from ops_platform.websocket import ws_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/alerts", tags=["alerts"])


def _fingerprint(payload: AlertCreate) -> str:
    if payload.fingerprint:
        return payload.fingerprint
    raw = f"{payload.agent_id}:{payload.type}:{payload.message}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.get("", response_model=list[AlertRead])
async def list_alerts(
    status_filter: str | None = Query(default=None, alias="status"),
    agent_id: str | None = None,
    severity: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Alert).where(Alert.tenant_id == current_user.tenant_id)
    if status_filter:
        query = query.where(Alert.status == status_filter)
    if agent_id:
        query = query.where(Alert.agent_id == agent_id)
    if severity:
        query = query.where(Alert.severity == severity)
    result = await db.execute(query.order_by(Alert.created_at.desc()).offset(offset).limit(limit))
    return result.scalars().all()


@router.post("", response_model=AlertRead, status_code=201)
async def create_alert(
    payload: AlertCreate,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    if payload.agent_id != agent_context.agent_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="agent id mismatch")

    result = await db.execute(select(Agent).where(Agent.agent_id == payload.agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")

    alert = Alert(
        tenant_id=agent_context.tenant_id,
        agent_id=payload.agent_id,
        type=payload.type,
        severity=payload.severity,
        message=payload.message,
        status=payload.status,
        details=payload.details,
        fingerprint=_fingerprint(payload),
    )
    db.add(alert)
    await db.commit()
    await db.refresh(alert)

    # WebSocket 广播
    from ops_platform.scheduler import broadcast_alert_ws, send_alert_notifications
    await broadcast_alert_ws(alert)

    # 发送通知
    await send_alert_notifications(
        db=db,
        tenant_id=agent_context.tenant_id,
        agent_id=alert.agent_id,
        agent_hostname=agent.hostname,
        alert_type=alert.type,
        severity=alert.severity,
        message=alert.message,
        details=alert.details,
        alert_id=alert.id,
    )
    await db.commit()

    return alert


@router.post("/agent", response_model=AlertRead, status_code=201)
async def create_alert_compat(
    payload: AlertCreate,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    return await create_alert(payload, agent_context, db)


@router.post("/{alert_id}/resolve", response_model=AlertRead)
async def resolve_alert(
    alert_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动解决告警"""
    result = await db.execute(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.tenant_id == current_user.tenant_id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "告警不存在")
    if alert.status not in ("open", "acknowledged"):
        raise HTTPException(400, f"告警当前状态为 {alert.status}，无法解决")
    alert.status = "resolved"
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "resolve", "alert", str(alert_id))
    await db.refresh(alert)
    return alert


@router.post("/{alert_id}/acknowledge", response_model=AlertRead)
async def acknowledge_alert(
    alert_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """确认告警（已收到，处理中）"""
    result = await db.execute(
        select(Alert).where(
            Alert.id == alert_id,
            Alert.tenant_id == current_user.tenant_id,
        )
    )
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "告警不存在")
    if alert.status != "open":
        raise HTTPException(400, f"告警当前状态为 {alert.status}，无法确认")
    alert.status = "acknowledged"
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "acknowledge", "alert", str(alert_id))
    await db.refresh(alert)
    return alert
