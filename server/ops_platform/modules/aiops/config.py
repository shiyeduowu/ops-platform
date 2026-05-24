"""AIOps 模块配置 — 管理 AI 相关设置"""
from __future__ import annotations

import os
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIOpsConfig:
    """AI 运维模块配置（从环境变量读取）"""

    # 是否全局启用 AI Agent（可通过 per-tenant 配置覆盖）
    enabled: bool = field(default_factory=lambda: os.getenv("AIOPS_ENABLED", "false").lower() == "true")

    # LLM 配置（OpenAI-compatible 接口）
    api_key: str = field(default_factory=lambda: os.getenv("AIOPS_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("AIOPS_BASE_URL", "https://api.openai.com/v1"))
    model: str = field(default_factory=lambda: os.getenv("AIOPS_MODEL", "gpt-4o-mini"))
    max_tokens: int = field(default_factory=lambda: int(os.getenv("AIOPS_MAX_TOKENS", "4096")))
    temperature: float = field(default_factory=lambda: float(os.getenv("AIOPS_TEMPERATURE", "0.1")))

    # Tool calling 配置
    max_tool_rounds: int = field(default_factory=lambda: min(int(os.getenv("AIOPS_MAX_TOOL_ROUNDS", "10")), 20))

    # RAG 配置
    rag_enabled: bool = field(default_factory=lambda: os.getenv("AIOPS_RAG_ENABLED", "true").lower() == "true")
    rag_embedding_model: str = field(default_factory=lambda: os.getenv("AIOPS_RAG_EMBEDDING_MODEL", "all-MiniLM-L6-v2"))
    rag_top_k: int = field(default_factory=lambda: int(os.getenv("AIOPS_RAG_TOP_K", "5")))

    # ChromaDB 配置
    chroma_persist_dir: str = field(default_factory=lambda: os.getenv("AIOPS_CHROMA_DIR", "./data/chromadb"))

    def is_available(self) -> bool:
        """检查 AI 模块是否可用（已启用且配置了 API key）"""
        return self.enabled and bool(self.api_key)


aiops_config = AIOpsConfig()

# 启动时打印 AI 配置摘要
if aiops_config.enabled:
    logger.info("AIOps 模块已启用 | model=%s | base_url=%s", aiops_config.model, aiops_config.base_url)
else:
    logger.info("AIOps 模块未启用（设置 AIOPS_ENABLED=true 并配置 AIOPS_API_KEY 以开启）")
