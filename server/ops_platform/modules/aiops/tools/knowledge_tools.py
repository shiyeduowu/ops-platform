"""知识库检索工具"""
from __future__ import annotations

from typing import Any

from ops_platform.modules.aiops.tools import tool
from ops_platform.modules.aiops.rag.store import search, get_collection_stats


@tool(
    name="search_knowledge",
    description="从知识库中语义检索相关文档（历史告警、运维经验、脚本说明等）",
    parameters={
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "搜索关键词或问题描述",
            },
            "top_k": {
                "type": "integer",
                "description": "返回结果数量，默认 5",
            },
        },
        "required": ["query"],
    },
)
async def search_knowledge(tenant_id: int, query: str = "", top_k: int = 5, **kw) -> dict:
    top_k = min(max(1, int(top_k)), 20)
    results = search(tenant_id, query, top_k=top_k)
    return {
        "query": query,
        "result_count": len(results),
        "results": results,
    }


@tool(
    name="get_knowledge_stats",
    description="获取知识库统计信息（文档数量等）",
    parameters={
        "type": "object",
        "properties": {},
        "required": [],
    },
)
async def get_knowledge_stats(tenant_id: int, **kw) -> dict:
    return get_collection_stats(tenant_id)
