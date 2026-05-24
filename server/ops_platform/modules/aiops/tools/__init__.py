"""Tool Registry — 注册和管理所有 AI 可调用的工具"""
from __future__ import annotations

import logging
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# Tool 函数类型: async (tenant_id: int, db: AsyncSession, **kwargs) -> dict
ToolFunc = Callable[..., Awaitable[dict[str, Any]]]

# 全局 tool 注册表
_REGISTRY: dict[str, dict[str, Any]] = {}

# 需要用户确认的写操作工具（LLM 不可自动调用）
_WRITE_TOOLS: set[str] = {"acknowledge_alert"}


def tool(name: str, description: str, parameters: dict[str, Any]):
    """装饰器：注册一个 tool"""

    def decorator(func: ToolFunc) -> ToolFunc:
        _REGISTRY[name] = {
            "name": name,
            "description": description,
            "parameters": parameters,
            "func": func,
        }
        return func

    return decorator


def get_all_tools() -> list[dict[str, Any]]:
    """获取所有只读 tool 定义（LLM 可自动调用的，不含写操作）"""
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"],
            },
        }
        for t in _REGISTRY.values()
        if t["name"] not in _WRITE_TOOLS
    ]


async def execute_tool(name: str, tenant_id: int, db: Any, arguments: dict[str, Any]) -> dict[str, Any]:
    """执行一个 tool（仅限只读工具）"""
    if name not in _REGISTRY:
        return {"error": "未知工具"}

    if name in _WRITE_TOOLS:
        return {"error": "该操作需要用户确认，AI 不可自动执行"}

    func = _REGISTRY[name]["func"]
    try:
        return await func(tenant_id=tenant_id, db=db, **arguments)
    except Exception:
        logger.exception("Tool %s execution failed", name)
        return {"error": "工具执行失败，请稍后再试"}


# 导入所有 tool 模块以触发注册
from ops_platform.modules.aiops.tools import (  # noqa: E402, F401
    host_tools,
    alert_tools,
    script_tools,
    metric_tools,
    system_tools,
    knowledge_tools,
)
