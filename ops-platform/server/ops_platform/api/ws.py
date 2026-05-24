from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
import jwt as pyjwt
from jwt import PyJWTError as JWTError

from ops_platform.core.config import settings
from ops_platform.db import AsyncSessionLocal
from ops_platform.models import Agent
from ops_platform.websocket import ws_manager


logger = logging.getLogger(__name__)
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/agent/{agent_id}")
async def agent_stream(
    agent_id: str,
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    # WebSocket 认证：通过 query param 或 subprotocol 传递 token
    if not token:
        # 尝试从 header 获取
        token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        await websocket.close(code=4001, reason="missing token")
        return
    try:
        payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            await websocket.close(code=4001, reason="invalid token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="invalid token")
        return

    # 校验 Agent 是否属于该租户
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select
        result = await db.execute(
            select(Agent).where(Agent.agent_id == agent_id, Agent.tenant_id == tenant_id)
        )
        if result.scalar_one_or_none() is None:
            await websocket.close(code=4003, reason="agent not found in tenant")
            return

    await ws_manager.connect(agent_id, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(agent_id, websocket)
    except Exception:
        ws_manager.disconnect(agent_id, websocket)


@router.websocket("/ws/dashboard")
async def dashboard_stream(
    websocket: WebSocket,
    token: str | None = Query(default=None),
):
    """全局仪表盘 WebSocket — 接收所有告警和任务完成事件"""
    if not token:
        token = websocket.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token:
        await websocket.close(code=4001, reason="missing token")
        return
    try:
        payload = pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        tenant_id = payload.get("tenant_id")
        if not tenant_id:
            await websocket.close(code=4001, reason="invalid token")
            return
    except JWTError:
        await websocket.close(code=4001, reason="invalid token")
        return

    channel = f"_dashboard_{tenant_id}"
    await ws_manager.connect(channel, websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(channel, websocket)
    except Exception:
        ws_manager.disconnect(channel, websocket)
