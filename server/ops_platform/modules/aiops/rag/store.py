"""ChromaDB 向量存储封装"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ops_platform.modules.aiops.config import aiops_config

logger = logging.getLogger(__name__)

# 延迟导入 ChromaDB（首次使用时初始化）
_chroma_client = None
_embedding_fn = None


def _get_chroma_client():
    """获取或创建 ChromaDB 客户端（持久化存储）"""
    global _chroma_client
    if _chroma_client is None:
        import chromadb

        persist_dir = aiops_config.chroma_persist_dir
        Path(persist_dir).mkdir(parents=True, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(path=persist_dir)
        logger.info("ChromaDB 初始化完成, persist_dir=%s", persist_dir)
    return _chroma_client


def _get_embedding_fn():
    """获取 embedding 函数（使用 sentence-transformers）"""
    global _embedding_fn
    if _embedding_fn is None:
        try:
            from chromadb.utils import embedding_functions

            _embedding_fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=aiops_config.rag_embedding_model
            )
            logger.info("Embedding 模型加载完成: %s", aiops_config.rag_embedding_model)
        except ImportError:
            logger.warning("sentence-transformers 未安装，RAG 功能不可用")
            return None
    return _embedding_fn


def get_or_create_collection(tenant_id: int):
    """获取或创建租户专属的 ChromaDB collection"""
    client = _get_chroma_client()
    embedding_fn = _get_embedding_fn()
    if embedding_fn is None:
        return None

    collection_name = f"tenant_{tenant_id}_knowledge"
    return client.get_or_create_collection(
        name=collection_name,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )


def add_documents(tenant_id: int, doc_ids: list[str], texts: list[str], metadatas: list[dict] = None) -> bool:
    """添加文档到向量库"""
    collection = get_or_create_collection(tenant_id)
    if collection is None:
        return False

    try:
        collection.add(ids=doc_ids, documents=texts, metadatas=metadatas or [{}] * len(doc_ids))
        logger.info("Added %d documents to tenant %d RAG", len(doc_ids), tenant_id)
        return True
    except Exception:
        logger.exception("Failed to add documents to RAG")
        return False


def search(tenant_id: int, query: str, top_k: int = None) -> list[dict[str, Any]]:
    """语义检索"""
    collection = get_or_create_collection(tenant_id)
    if collection is None:
        return []

    if top_k is None:
        top_k = aiops_config.rag_top_k

    try:
        results = collection.query(query_texts=[query], n_results=top_k)
        docs = []
        for i, doc_id in enumerate(results["ids"][0]):
            docs.append({
                "id": doc_id,
                "content": results["documents"][0][i],
                "distance": results["distances"][0][i] if results.get("distances") else None,
                "metadata": results["metadatas"][0][i] if results.get("metadatas") else {},
            })
        return docs
    except Exception:
        logger.exception("RAG search failed")
        return []


def delete_documents(tenant_id: int, doc_ids: list[str]) -> bool:
    """删除文档"""
    collection = get_or_create_collection(tenant_id)
    if collection is None:
        return False

    try:
        collection.delete(ids=doc_ids)
        return True
    except Exception:
        logger.exception("Failed to delete documents from RAG")
        return False


def get_collection_stats(tenant_id: int) -> dict[str, Any]:
    """获取 collection 统计信息"""
    collection = get_or_create_collection(tenant_id)
    if collection is None:
        return {"available": False, "count": 0}

    try:
        count = collection.count()
        return {"available": True, "count": count}
    except Exception:
        return {"available": False, "count": 0}
