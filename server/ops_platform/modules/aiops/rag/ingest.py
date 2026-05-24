"""文档摄入 — 将告警、巡检报告、脚本说明等自动入库 RAG"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.models import Alert, KnowledgeDocument, RemoteCommand
from ops_platform.modules.aiops.rag.store import add_documents

logger = logging.getLogger(__name__)


async def ingest_document(db: AsyncSession, doc_id: int) -> bool:
    """将一条 KnowledgeDocument 向量化并存入 ChromaDB"""
    result = await db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == doc_id))
    doc = result.scalar_one_or_none()
    if not doc:
        return False

    success = add_documents(
        tenant_id=doc.tenant_id,
        doc_ids=[f"doc_{doc.id}"],
        texts=[doc.content],
        metadatas=[{"title": doc.title, "source_type": doc.source_type, "source_id": doc.source_id or ""}],
    )

    # 更新状态
    doc.embedding_status = "done" if success else "failed"
    await db.commit()
    return success


async def ingest_alert_to_knowledge(db: AsyncSession, alert_id: int) -> bool:
    """将已确认/解决的告警自动入库知识库"""
    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    if not alert:
        return False

    content = f"告警类型: {alert.type}\n严重级别: {alert.severity}\n主机: {alert.agent_id}\n消息: {alert.message}"
    if alert.details:
        content += f"\n详情: {alert.details}"

    doc = KnowledgeDocument(
        tenant_id=alert.tenant_id,
        title=f"[告警] {alert.type} - {alert.agent_id}",
        content=content,
        source_type="alert",
        source_id=str(alert.id),
        embedding_status="pending",
    )
    db.add(doc)
    await db.flush()

    return await ingest_document(db, doc.id)


async def ingest_pending_documents(db: AsyncSession) -> int:
    """批量摄入所有 pending 状态的文档"""
    result = await db.execute(
        select(KnowledgeDocument).where(KnowledgeDocument.embedding_status == "pending").limit(50)
    )
    docs = result.scalars().all()

    success_count = 0
    for doc in docs:
        if await ingest_document(db, doc.id):
            success_count += 1

    if success_count > 0:
        logger.info("RAG 批量摄入完成: %d/%d 成功", success_count, len(docs))

    return success_count
