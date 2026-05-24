"""AIOps API 路由 — AI 对话、配置管理、知识库"""
from __future__ import annotations

import json
import logging
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user, get_db
from ops_platform.models import AiopsConfig, KnowledgeDocument
from ops_platform.modules.aiops.config import aiops_config
from ops_platform.modules.aiops.router import AIRouter
from ops_platform.schemas import UserContext

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/aiops", tags=["AIOps"])

# ─────────────────────── Pydantic Schemas ────────────────────────


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=10000)
    history: list[dict] = Field(default_factory=list, max_length=50)


class ConfigUpdateRequest(BaseModel):
    enabled: bool | None = None
    model_override: str | None = Field(default=None, max_length=100)


class KnowledgeIngestRequest(BaseModel):
    title: str = Field(..., min_length=1, max_length=500)
    content: str = Field(..., min_length=1, max_length=50000)


# ─────────────────────── 简单速率限制 ────────────────────────

_chat_rate_limit: dict[int, list[float]] = {}
_CHAT_RATE_WINDOW = 60.0
_CHAT_RATE_MAX = 20  # 每租户每分钟最多 20 次对话


def _check_chat_rate_limit(tenant_id: int) -> None:
    now = time.time()
    timestamps = _chat_rate_limit.setdefault(tenant_id, [])
    # 清理过期记录
    timestamps[:] = [t for t in timestamps if now - t < _CHAT_RATE_WINDOW]
    if len(timestamps) >= _CHAT_RATE_MAX:
        raise HTTPException(status_code=429, detail="AI 对话请求过于频繁，请稍后再试")
    timestamps.append(now)


# ─────────────────────── 对话 API（SSE 流式输出）───────────────────────


@router.post("/chat")
async def aiops_chat(
    body: ChatRequest,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """AI 对话接口（SSE 流式输出）"""
    _check_chat_rate_limit(current_user.tenant_id)

    check = await AIRouter.check_tenant(db, current_user.tenant_id)
    if not check["available"]:
        return StreamingResponse(
            _sse_degraded(check["reason"]),
            media_type="text/event-stream",
        )

    return StreamingResponse(
        _sse_chat_stream(body.message, body.history, current_user.tenant_id, db),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_degraded(reason: str) -> AsyncGenerator[str, None]:
    """降级响应（AI 不可用时）"""
    resp = AIRouter.get_degradation_response(reason)
    yield f"data: {json.dumps(resp, ensure_ascii=False)}\n\n"
    yield "data: [DONE]\n\n"


async def _sse_chat_stream(
    message: str,
    history: list[dict],
    tenant_id: int,
    db: AsyncSession,
) -> AsyncGenerator[str, None]:
    """SSE 流式对话 — 接入 AI Engine"""
    from ops_platform.modules.aiops.engine import aiops_engine

    async for chunk in aiops_engine.chat_stream(message, history, tenant_id, db):
        yield f"data: {chunk}\n\n"
    yield "data: [DONE]\n\n"


# ─────────────────────── 配置管理 API ────────────────────────


@router.get("/config")
async def get_aiops_config(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取当前租户的 AI 配置（仅管理员）"""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可查看 AI 配置")

    result = await db.execute(
        select(AiopsConfig).where(AiopsConfig.tenant_id == current_user.tenant_id)
    )
    config = result.scalar_one_or_none()

    global_check = AIRouter.check_global()

    return {
        "global_enabled": aiops_config.enabled,
        "global_available": global_check["available"],
        "global_reason": global_check["reason"],
        "model": aiops_config.model,
        "tenant_enabled": config.enabled if config else True,
        "model_override": config.model_override if config else None,
        "rag_enabled": aiops_config.rag_enabled,
    }


@router.put("/config")
async def update_aiops_config(
    body: ConfigUpdateRequest,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新当前租户的 AI 配置（仅管理员）"""
    if current_user.role not in ("owner", "admin"):
        raise HTTPException(status_code=403, detail="仅管理员可修改 AI 配置")

    result = await db.execute(
        select(AiopsConfig).where(AiopsConfig.tenant_id == current_user.tenant_id)
    )
    config = result.scalar_one_or_none()

    if config is None:
        config = AiopsConfig(tenant_id=current_user.tenant_id)
        db.add(config)

    if body.enabled is not None:
        config.enabled = body.enabled
    if body.model_override is not None:
        config.model_override = body.model_override or None

    await db.commit()
    return {"status": "ok"}


# ─────────────────────── 知识库 API ────────────────────────


@router.get("/knowledge")
async def list_knowledge(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取知识库文档列表"""
    base = (
        select(KnowledgeDocument)
        .where(KnowledgeDocument.tenant_id == current_user.tenant_id)
        .order_by(KnowledgeDocument.created_at.desc())
    )

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)

    result = await db.execute(base.offset(offset).limit(limit))
    items = result.scalars().all()

    return {
        "items": [
            {
                "id": doc.id,
                "title": doc.title,
                "source_type": doc.source_type,
                "embedding_status": doc.embedding_status,
                "created_at": doc.created_at.isoformat(),
            }
            for doc in items
        ],
        "total": total,
    }


@router.post("/knowledge/ingest")
async def ingest_knowledge(
    body: KnowledgeIngestRequest,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """手动摄入知识文档"""
    doc = KnowledgeDocument(
        tenant_id=current_user.tenant_id,
        title=body.title,
        content=body.content,
        source_type="manual",
        embedding_status="pending",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    return {"id": doc.id, "status": "ok", "message": "文档已提交，将在后台完成向量化"}
