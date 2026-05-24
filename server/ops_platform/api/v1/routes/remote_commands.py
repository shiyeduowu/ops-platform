from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.db import get_db
from ops_platform.models import Agent, AgentConfig, RemoteCommand, RemoteCommandTarget
from ops_platform.schemas import (
    AgentAuthContext,
    PaginatedResponse,
    RemoteCommandCreate,
    RemoteCommandRead,
    RemoteCommandResultSubmit,
    UserContext,
)
from ops_platform.websocket import ws_manager


router = APIRouter(prefix="/remote-commands", tags=["remote-commands"])

# 白名单命令 — 两个平台的并集（Agent 端会按平台二次校验）
ALLOWED_SHELL_COMMANDS = {
    # Windows 基础
    "ipconfig", "hostname", "whoami", "systeminfo", "tasklist",
    "netstat", "ping", "dir", "type", "echo", "date", "time",
    "ver", "tree", "findstr",
    # POSIX 基础
    "df", "free", "uptime", "ps", "cat", "ls", "uname",
    "ifconfig", "dig", "nslookup", "traceroute", "tail", "head",
    "wc", "grep", "sort", "uniq", "du",
    # Windows 服务/进程管理
    "sc", "net", "wmic", "taskkill", "schtasks",
    # 进程管理 (POSIX)
    "top", "kill", "pkill", "lsof", "ss", "vmstat", "iostat",
    # Java 诊断
    "java", "jstack", "jmap", "jcmd", "jps", "jstat", "jinfo",
    # 数据库 CLI
    "mysql", "redis-cli", "sqlplus", "sqlite3", "mongosh",
    # Python/Node 诊断
    "python", "python3", "pip",
}

# 危险的 shell 元字符
_SHELL_META = re.compile(r"[;|&$`\\(){}!\n\r]")


def _validate_command(command_type: str, command_text: str) -> None:
    if not command_text.strip():
        raise HTTPException(status_code=400, detail="命令不能为空")
    # 检测 shell 元字符（防止注入）
    if _SHELL_META.search(command_text):
        raise HTTPException(status_code=400, detail="命令包含不允许的特殊字符（;|&$` 等）")
    # 提取首单词（命令名）
    first_word = command_text.strip().split()[0].lower()
    # 去除路径前缀（如 /bin/ls -> ls）
    if "/" in first_word:
        first_word = first_word.rsplit("/", 1)[-1]
    if "\\" in first_word:
        first_word = first_word.rsplit("\\", 1)[-1]
    if first_word not in ALLOWED_SHELL_COMMANDS:
        raise HTTPException(
            status_code=400,
            detail=f"不允许的命令: {first_word}。白名单: {', '.join(sorted(ALLOWED_SHELL_COMMANDS))}",
        )


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", response_model=RemoteCommandRead, status_code=201)
async def create_remote_command(
    payload: RemoteCommandCreate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_command(payload.command_type, payload.command_text)

    # 验证目标 Agent 存在且属于当前租户
    agents_result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.agent_id.in_(payload.target_agent_ids),
        )
    )
    found_agents = list(agents_result.scalars().all())
    if len(found_agents) != len(payload.target_agent_ids):
        found_ids = {a.agent_id for a in found_agents}
        missing = set(payload.target_agent_ids) - found_ids
        raise HTTPException(status_code=400, detail=f"Agent 不存在: {missing}")

    cmd = RemoteCommand(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        command_type=payload.command_type,
        command_text=payload.command_text,
        timeout_seconds=payload.timeout_seconds,
        status="draft",
        created_by=current_user.username,
    )
    db.add(cmd)
    await db.flush()

    for agent_id in payload.target_agent_ids:
        db.add(RemoteCommandTarget(command_id=cmd.id, agent_id=agent_id))

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "create", "remote_command", str(cmd.id))

    result = await db.execute(
        select(RemoteCommand)
        .options(selectinload(RemoteCommand.targets))
        .where(RemoteCommand.id == cmd.id)
    )
    return result.scalar_one()


@router.get("", response_model=PaginatedResponse[RemoteCommandRead])
async def list_remote_commands(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(RemoteCommand).where(RemoteCommand.tenant_id == current_user.tenant_id)
    if status_filter:
        base = base.where(RemoteCommand.status == status_filter)
    if search:
        base = base.where(RemoteCommand.name.ilike(f"%{search}%"))

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)

    result = await db.execute(
        base.options(selectinload(RemoteCommand.targets))
        .order_by(RemoteCommand.created_at.desc())
        .offset(offset).limit(limit)
    )
    return {"items": result.scalars().all(), "total": total}


@router.get("/{command_id}", response_model=RemoteCommandRead)
async def get_remote_command(
    command_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RemoteCommand)
        .options(selectinload(RemoteCommand.targets))
        .where(RemoteCommand.id == command_id, RemoteCommand.tenant_id == current_user.tenant_id)
    )
    cmd = result.scalar_one_or_none()
    if cmd is None:
        raise HTTPException(status_code=404, detail="命令不存在")
    return cmd


@router.post("/{command_id}/start", response_model=RemoteCommandRead)
async def start_remote_command(
    command_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RemoteCommand)
        .options(selectinload(RemoteCommand.targets))
        .where(RemoteCommand.id == command_id, RemoteCommand.tenant_id == current_user.tenant_id)
    )
    cmd = result.scalar_one_or_none()
    if cmd is None:
        raise HTTPException(status_code=404, detail="命令不存在")
    if cmd.status not in ("draft", "failed"):
        raise HTTPException(status_code=400, detail=f"当前状态 {cmd.status} 无法启动")

    now = _utcnow()
    cmd.status = "pending"
    cmd.started_at = now
    for target in cmd.targets:
        target.status = "pending"

    # 加速心跳让 Agent 更快拉取命令
    agent_ids = [t.agent_id for t in cmd.targets]
    configs_result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
    )
    for cfg in configs_result.scalars().all():
        config = dict(cfg.config_json)
        config["heartbeat_override_seconds"] = 10
        cfg.config_json = config
        cfg.config_version = f"v{int(time.time())}"

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "start", "remote_command", str(command_id))

    result = await db.execute(
        select(RemoteCommand)
        .options(selectinload(RemoteCommand.targets))
        .where(RemoteCommand.id == cmd.id)
    )
    return result.scalar_one()


@router.delete("/{command_id}", status_code=204)
async def delete_remote_command(
    command_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RemoteCommand).where(
            RemoteCommand.id == command_id,
            RemoteCommand.tenant_id == current_user.tenant_id,
        )
    )
    cmd = result.scalar_one_or_none()
    if cmd is None:
        raise HTTPException(status_code=404, detail="命令不存在")
    if cmd.status == "running":
        raise HTTPException(status_code=400, detail="运行中的命令无法删除")

    await db.delete(cmd)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "delete", "remote_command", str(command_id))


@router.post("/agent/result")
async def agent_submit_command_result(
    payload: RemoteCommandResultSubmit,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    # 验证该 Agent 是此命令的目标
    target_result = await db.execute(
        select(RemoteCommandTarget).join(RemoteCommand).where(
            RemoteCommandTarget.command_id == payload.command_id,
            RemoteCommandTarget.agent_id == agent_context.agent_id,
            RemoteCommand.tenant_id == agent_context.tenant_id,
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="未找到对应的命令目标")

    now = _utcnow()
    target.status = "completed" if payload.exit_code == 0 else "failed"
    target.stdout = payload.stdout[:100000]
    target.stderr = payload.stderr[:100000]
    target.exit_code = payload.exit_code
    target.finished_at = now

    # 广播结果到前端
    await ws_manager.broadcast(
        agent_context.agent_id,
        {
            "event": "remote_command_result",
            "command_id": payload.command_id,
            "agent_id": agent_context.agent_id,
            "status": target.status,
            "exit_code": payload.exit_code,
        },
    )

    # 检查是否所有目标都已完成
    all_targets_result = await db.execute(
        select(RemoteCommandTarget).where(RemoteCommandTarget.command_id == payload.command_id)
    )
    all_targets = list(all_targets_result.scalars().all())
    if all(t.status in ("completed", "failed") for t in all_targets):
        cmd_result = await db.execute(
            select(RemoteCommand).where(RemoteCommand.id == payload.command_id)
        )
        cmd = cmd_result.scalar_one_or_none()
        if cmd and cmd.status in ("pending", "running"):
            has_failed = any(t.status == "failed" for t in all_targets)
            cmd.status = "failed" if has_failed else "completed"

            # 发送完成通知
            from ops_platform.scheduler import notify_task_completion
            await notify_task_completion(
                db=db,
                tenant_id=cmd.tenant_id,
                task_type="remote_command",
                task_id=cmd.id,
                task_name=cmd.name,
                success=not has_failed,
            )

            # 恢复心跳间隔
            agent_ids = [t.agent_id for t in all_targets]
            configs_result = await db.execute(
                select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
            )
            for cfg in configs_result.scalars().all():
                config = dict(cfg.config_json)
                config.pop("heartbeat_override_seconds", None)
                cfg.config_json = config
                cfg.config_version = f"v{int(time.time())}"

    await db.commit()
    return {"ok": True}
