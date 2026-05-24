"""AI Engine — 管理对话、调用 LLM、执行 Tool Calls"""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncGenerator

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.modules.aiops.config import aiops_config
from ops_platform.modules.aiops.tools import get_all_tools, execute_tool

logger = logging.getLogger(__name__)

# System prompt 引导 AI 行为
SYSTEM_PROMPT = """你是一个智能运维助手，帮助用户管理和监控服务器基础设施。

你可以：
- 查看主机状态、指标、分组信息
- 查看和确认告警
- 查询脚本执行结果
- 查询历史指标数据
- 获取系统总览
- 查看部署和分发任务

请用简洁专业的中文回答。当用户询问主机或告警状态时，主动调用相关工具获取实时数据。
如果用户的问题超出你的能力范围，请诚实说明。"""


class AIOpsEngine:
    """AI 运维引擎 — 对话管理 + LLM 调用 + Tool 执行"""

    def __init__(self):
        self.base_url = aiops_config.base_url.rstrip("/")
        self.model = aiops_config.model
        self.max_tokens = aiops_config.max_tokens
        self.temperature = aiops_config.temperature
        self.max_tool_rounds = aiops_config.max_tool_rounds

    async def chat_stream(
        self,
        message: str,
        history: list[dict[str, str]],
        tenant_id: int,
        db: AsyncSession,
    ) -> AsyncGenerator[str, None]:
        """
        流式对话：发送消息 → LLM → 可能多轮 tool call → 流式输出

        Yields SSE 格式的 data 行内容（不含 "data: " 前缀和 "\n\n" 后缀）
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend(history[-20:])  # 保留最近 20 条历史
        messages.append({"role": "user", "content": message})

        tools = get_all_tools()

        for round_idx in range(self.max_tool_rounds):
            # 调用 LLM
            llm_response = await self._call_llm(messages, tools)
            if "error" in llm_response:
                yield json.dumps({"role": "assistant", "content": f"AI 服务错误: {llm_response['error']}", "tool_calls": None}, ensure_ascii=False)
                return

            choice = llm_response.get("choices", [{}])[0]
            assistant_msg = choice.get("message", {})
            finish_reason = choice.get("finish_reason", "")

            # 如果有 tool_calls，执行它们
            tool_calls = assistant_msg.get("tool_calls")
            if tool_calls and finish_reason == "tool_calls":
                # 先通知前端正在调用工具
                for tc in tool_calls:
                    fn_name = tc["function"]["name"]
                    yield json.dumps({
                        "type": "tool_call",
                        "tool_name": fn_name,
                        "arguments": tc["function"].get("arguments", "{}"),
                    }, ensure_ascii=False)

                # 把 assistant 消息加入历史
                messages.append(assistant_msg)

                # 执行每个 tool call
                for tc in tool_calls:
                    tc_id = tc["id"]
                    fn_name = tc["function"]["name"]
                    try:
                        fn_args = json.loads(tc["function"].get("arguments", "{}"))
                    except json.JSONDecodeError:
                        fn_args = {}

                    result = await execute_tool(fn_name, tenant_id, db, fn_args)
                    result_str = json.dumps(result, ensure_ascii=False, default=str)

                    # 通知前端 tool 执行结果
                    yield json.dumps({
                        "type": "tool_result",
                        "tool_name": fn_name,
                        "result_preview": result_str[:500],
                    }, ensure_ascii=False)

                    # 把 tool result 加入 messages
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "content": result_str,
                    })

                # 继续下一轮（LLM 看到 tool 结果后生成最终回复）
                continue

            # 没有 tool_calls，输出最终回复
            content = assistant_msg.get("content", "")
            yield json.dumps({"role": "assistant", "content": content, "tool_calls": None}, ensure_ascii=False)
            return

        # 超过最大轮次
        yield json.dumps({"role": "assistant", "content": "AI 处理轮次过多，请简化您的问题。", "tool_calls": None}, ensure_ascii=False)

    async def _call_llm(self, messages: list[dict], tools: list[dict] = None) -> dict[str, Any]:
        """调用 OpenAI-compatible LLM API"""
        headers = {
            "Authorization": f"Bearer {aiops_config.api_key}",
            "Content-Type": "application/json",
        }

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
        }

        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(
                    f"{self.base_url}/chat/completions",
                    headers=headers,
                    json=payload,
                )
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("LLM API HTTP error: %s %s", e.response.status_code, e.response.text[:500])
            return {"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
        except httpx.RequestError as e:
            logger.error("LLM API request error: %s", e)
            return {"error": f"请求失败: {str(e)}"}


# 全局引擎实例
aiops_engine = AIOpsEngine()
