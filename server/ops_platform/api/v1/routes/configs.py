from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.core.utils import next_version
from ops_platform.db import get_db
from ops_platform.models import Agent, AgentConfig
from ops_platform.schemas import ConfigRead, ConfigUpdate, UserContext
from ops_platform.websocket import ws_manager


router = APIRouter(prefix="/config", tags=["config"])

AGENT_CONFIG_SCHEMA = {
    "port_checks": {
        "label": "端口检测列表",
        "type": "port_list",
        "hint": "Agent 本地检测的 TCP 端口列表，支持 dict 格式（host/port/service_key/name）或纯端口号",
        "default": [],
    },
    "log_sources": {
        "label": "日志采集源",
        "type": "log_source_list",
        "hint": "日志文件路径和服务标识，Agent 会 tail 这些文件并匹配关键词",
        "default": [],
        "fields": {
            "path": {"label": "日志路径", "type": "text", "placeholder": "C:\\logs\\app\\error.log"},
            "service_key": {"label": "服务标识", "type": "text", "placeholder": "my-service"},
            "encoding": {"label": "编码", "type": "text", "placeholder": "utf-8"},
            "max_lines_per_tick": {"label": "每次最大行数", "type": "number", "default": 200},
        },
    },
    "log_keywords": {
        "label": "日志告警关键词",
        "type": "tag_list",
        "hint": "匹配到这些关键词的日志行会触发告警，回车添加",
        "default": ["ERROR", "Exception", "FATAL"],
    },
    "disk_threshold": {
        "label": "磁盘剩余空间阈值",
        "type": "number",
        "unit": "%",
        "hint": "磁盘剩余空间低于此百分比时触发告警",
        "default": 10,
        "min": 1,
        "max": 99,
    },
    "cpu_threshold": {
        "label": "CPU 使用率阈值",
        "type": "number",
        "unit": "%",
        "hint": "CPU 使用率超过此百分比时触发告警",
        "default": 90,
        "min": 1,
        "max": 100,
    },
    "memory_threshold": {
        "label": "内存使用率阈值",
        "type": "number",
        "unit": "%",
        "hint": "内存使用率超过此百分比时触发告警",
        "default": 90,
        "min": 1,
        "max": 100,
    },
    "check_interval_seconds": {
        "label": "本地检测间隔",
        "type": "number",
        "unit": "秒",
        "hint": "Agent 本地高频自检的执行间隔",
        "default": 30,
        "min": 10,
        "max": 3600,
    },
    "heartbeat_interval_seconds": {
        "label": "心跳间隔",
        "type": "number",
        "unit": "秒",
        "hint": "Agent 向 Server 发送心跳的间隔，仅作为存活证明",
        "default": 7200,
        "min": 60,
        "max": 86400,
    },
    "service_catalog": {
        "label": "服务目录",
        "type": "service_catalog_list",
        "hint": "定义服务元数据，关联端口、进程、日志的统一 service_key",
        "default": [],
        "fields": {
            "service_key": {"label": "服务标识", "type": "text", "placeholder": "my-app"},
            "name": {"label": "服务名称", "type": "text", "placeholder": "我的应用"},
            "product_line": {"label": "产品线", "type": "text", "placeholder": "核心业务"},
            "owner": {"label": "负责人", "type": "text", "placeholder": "张三"},
            "description": {"label": "描述", "type": "text", "placeholder": "主要业务服务"},
        },
    },
    "windows_services": {
        "label": "Windows 服务监控",
        "type": "tag_list",
        "hint": "需要监控的 Windows 服务名，回车添加。Agent 会检测这些服务是否 RUNNING",
        "default": [],
    },
    "log_discovery": {
        "label": "日志自动发现",
        "type": "log_discovery_list",
        "hint": "自动扫描目录下的 */logs/ 子目录并 tail 新日志文件",
        "default": [],
        "fields": {
            "root": {"label": "扫描根目录", "type": "text", "placeholder": "C:\\apps"},
            "glob": {"label": "文件匹配", "type": "text", "placeholder": "*.log"},
            "service_key": {"label": "服务标识模板", "type": "text", "placeholder": "{folder}"},
            "id_prefix": {"label": "ID 前缀", "type": "text", "placeholder": ""},
            "scan_interval_seconds": {"label": "扫描间隔(秒)", "type": "number", "default": 45},
        },
    },
    "stack_date_line_regex": {
        "label": "堆栈日期行正则",
        "type": "text",
        "hint": "用于识别日志新记录起始行的正则表达式，多行堆栈会聚合后匹配关键词",
        "default": r"^\d{4}-\d{2}-\d{2}",
    },
    "max_concurrent_tails": {
        "label": "最大并发 tail 数",
        "type": "number",
        "hint": "同时 tail 的日志文件数量上限，防止线程过多",
        "default": 48,
        "min": 1,
        "max": 200,
    },
    "log_cleanup_enabled": {
        "label": "启用日志清理",
        "type": "boolean",
        "hint": "自动删除过期的日志文件",
        "default": False,
    },
    "log_cleanup_retention_days": {
        "label": "日志保留天数",
        "type": "number",
        "unit": "天",
        "hint": "超过此天数的日志文件将被清理",
        "default": 30,
        "min": 1,
        "max": 365,
    },
    "log_cleanup_dry_run": {
        "label": "日志清理试运行",
        "type": "boolean",
        "hint": "开启后只打印将删除的文件，不实际删除",
        "default": True,
    },
    "log_cleanup_interval_seconds": {
        "label": "日志清理间隔",
        "type": "number",
        "unit": "秒",
        "hint": "日志清理任务的执行间隔",
        "default": 3600,
        "min": 60,
        "max": 86400,
    },
}


@router.get("/schema")
async def get_config_schema(
    current_user: UserContext = Depends(get_current_user),
):
    """返回 Agent 配置的 Schema 描述，供前端动态渲染表单"""
    return {"schema": AGENT_CONFIG_SCHEMA}


async def _get_tenant_agent(db: AsyncSession, tenant_id: int, agent_id: str) -> Agent:
    result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == tenant_id,
            Agent.agent_id == agent_id,
        )
    )
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="agent not found")
    return agent


@router.get("/{agent_id}", response_model=ConfigRead)
async def get_config(
    agent_id: str,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_tenant_agent(db, current_user.tenant_id, agent_id)
    result = await db.execute(select(AgentConfig).where(AgentConfig.agent_id == agent_id))
    config = result.scalar_one_or_none()
    if config is None:
        config = AgentConfig(agent_id=agent_id, config_json={}, config_version="v1")
        db.add(config)
        await db.commit()
        await db.refresh(config)
    return config


@router.put("/{agent_id}", response_model=ConfigRead)
async def update_config(
    agent_id: str,
    payload: ConfigUpdate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_tenant_agent(db, current_user.tenant_id, agent_id)
    result = await db.execute(select(AgentConfig).where(AgentConfig.agent_id == agent_id))
    config = result.scalar_one_or_none()
    if config is None:
        config = AgentConfig(agent_id=agent_id, config_json=payload.config_json, config_version="v1")
        db.add(config)
    else:
        config.config_json = payload.config_json
        config.config_version = payload.config_version or next_version(config.config_version)
        config.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(config)

    await ws_manager.broadcast(
        agent_id,
        {
            "event": "config",
            "agent_id": agent_id,
            "config_version": config.config_version,
        },
    )
    return config
