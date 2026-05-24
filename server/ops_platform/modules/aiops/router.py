"""全局策略路由 — 控制 AI 功能的启用/降级"""
from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.modules.aiops.config import aiops_config, AIOpsConfig

logger = logging.getLogger(__name__)


class AIRouter:
    """
    全局策略路由器：
    - 检查全局开关 + per-tenant 配置
    - AI 不可用时返回引导提示（不报错）
    """

    @staticmethod
    def check_global() -> dict[str, Any]:
        """检查全局 AI 可用性"""
        if not aiops_config.enabled:
            return {
                "available": False,
                "reason": "ai_disabled",
                "message": "AI 功能未启用。请联系管理员在环境变量中设置 AIOPS_ENABLED=true",
            }
        if not aiops_config.api_key:
            return {
                "available": False,
                "reason": "no_api_key",
                "message": "AI API Key 未配置。请联系管理员设置 AIOPS_API_KEY",
            }
        return {"available": True, "reason": "ok", "message": ""}

    @staticmethod
    async def check_tenant(db: AsyncSession, tenant_id: int) -> dict[str, Any]:
        """检查租户级别的 AI 可用性"""
        global_check = AIRouter.check_global()
        if not global_check["available"]:
            return global_check

        # 检查 per-tenant 配置
        from ops_platform.models import AiopsConfig as AiopsConfigModel

        result = await db.execute(
            select(AiopsConfigModel).where(AiopsConfigModel.tenant_id == tenant_id)
        )
        tenant_config = result.scalar_one_or_none()

        if tenant_config and not tenant_config.enabled:
            return {
                "available": False,
                "reason": "tenant_disabled",
                "message": "当前租户的 AI 功能已关闭。请在设置中启用。",
            }

        return {"available": True, "reason": "ok", "message": ""}

    @staticmethod
    def get_degradation_response(reason: str) -> dict[str, Any]:
        """获取降级响应（AI 不可用时返回给前端）"""
        messages = {
            "ai_disabled": "AI 功能未启用，请联系管理员开启。",
            "no_api_key": "AI API Key 未配置，请联系管理员设置。",
            "tenant_disabled": "当前租户的 AI 功能已关闭，请在设置中启用。",
            "llm_error": "AI 服务暂时不可用，请稍后再试。",
            "rate_limited": "AI 请求过于频繁，请稍后再试。",
        }
        return {
            "role": "assistant",
            "content": messages.get(reason, "AI 功能暂时不可用。"),
            "tool_calls": None,
            "degraded": True,
        }
