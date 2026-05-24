from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status, Query
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.core.config import settings
from ops_platform.db import get_db
from ops_platform.models import Agent, AgentConfig, FileDistribution, FileDistributionTarget
from ops_platform.schemas import (
    AgentAuthContext,
    FileDistributionRead,
    FileDistributionResultSubmit,
    PaginatedResponse,
    UserContext,
)
from ops_platform.websocket import ws_manager


router = APIRouter(prefix="/file-distributions", tags=["file-distributions"])

# 使用绝对路径，避免 CWD 不确定导致文件写到意外位置
UPLOAD_DIR = Path(__file__).resolve().parents[4] / "uploads" / "file_distributions"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
TOKEN_TTL_SECONDS = 3600  # 下载 token 1 小时过期

# 下载 token 存储（内存中，进程重启后失效）
_download_tokens: dict[str, tuple[int, float]] = {}  # token -> (distribution_id, created_at)


def _generate_download_token(distribution_id: int) -> str:
    token = uuid.uuid4().hex
    _download_tokens[token] = (distribution_id, time.time())
    return token


def _verify_download_token(token: str) -> int | None:
    entry = _download_tokens.pop(token, None)
    if entry is None:
        return None
    dist_id, created_at = entry
    if time.time() - created_at > TOKEN_TTL_SECONDS:
        return None
    return dist_id


def _cleanup_expired_tokens() -> None:
    """清理过期的下载 token"""
    now = time.time()
    expired = [k for k, (_, ts) in _download_tokens.items() if now - ts > TOKEN_TTL_SECONDS]
    for k in expired:
        _download_tokens.pop(k, None)


def _validate_target_path(target_path: str) -> None:
    """校验目标路径安全性"""
    if not target_path or not target_path.strip():
        raise HTTPException(status_code=400, detail="目标路径不能为空")
    # 禁止路径穿越
    if ".." in target_path:
        raise HTTPException(status_code=400, detail="目标路径不能包含 ..")
    # 禁止系统关键目录（Windows + Linux）
    normalized = target_path.replace("\\", "/").lower()
    forbidden = [
        "/etc/", "/bin/", "/sbin/", "/usr/", "/boot/", "/dev/", "/proc/", "/sys/",
        "c:/windows/", "c:/program files/", "c:/programdata/",
        "/system/", "/library/",
    ]
    for fb in forbidden:
        if normalized.startswith(fb) or normalized == fb.rstrip("/"):
            raise HTTPException(status_code=400, detail="禁止写入系统目录")


def _sanitize_filename(filename: str) -> str:
    """清理文件名中的特殊字符"""
    import re
    name = Path(filename).name
    # 只保留字母数字、横杠、下划线、点
    name = re.sub(r"[^\w\-.]", "_", name)
    return name or "uploaded_file"


def _compute_md5(file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", response_model=FileDistributionRead, status_code=201)
async def create_file_distribution(
    name: str = Form(...),
    target_path: str = Form(...),
    target_agent_ids: str = Form(...),  # JSON 数组字符串
    file: UploadFile = File(...),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import json

    # 解析目标 Agent IDs
    try:
        agent_ids = json.loads(target_agent_ids)
        if not isinstance(agent_ids, list) or not agent_ids:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="target_agent_ids 格式无效")

    # 验证文件大小
    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件不能为空")

    # 验证目标路径安全
    _validate_target_path(target_path)

    # 验证 Agent 存在
    agents_result = await db.execute(
        select(Agent).where(
            Agent.tenant_id == current_user.tenant_id,
            Agent.agent_id.in_(agent_ids),
        )
    )
    found_agents = list(agents_result.scalars().all())
    if len(found_agents) != len(agent_ids):
        found_ids = {a.agent_id for a in found_agents}
        missing = set(agent_ids) - found_ids
        raise HTTPException(status_code=400, detail=f"Agent 不存在: {missing}")

    # 保存文件
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    _cleanup_expired_tokens()
    filename = _sanitize_filename(file.filename or "uploaded_file")
    storage_name = f"{uuid.uuid4().hex}_{filename}"
    storage_path = UPLOAD_DIR / storage_name
    storage_path.write_bytes(content)

    md5 = _compute_md5(storage_path)

    dist = FileDistribution(
        tenant_id=current_user.tenant_id,
        name=name,
        filename=filename,
        storage_path=str(storage_path),
        target_path=target_path,
        file_size=len(content),
        checksum_md5=md5,
        status="draft",
        created_by=current_user.username,
    )
    db.add(dist)
    await db.flush()

    for agent_id in agent_ids:
        db.add(FileDistributionTarget(distribution_id=dist.id, agent_id=agent_id))

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "create", "file_distribution", str(dist.id))

    result = await db.execute(
        select(FileDistribution)
        .options(selectinload(FileDistribution.targets))
        .where(FileDistribution.id == dist.id)
    )
    return result.scalar_one()


@router.get("", response_model=PaginatedResponse[FileDistributionRead])
async def list_file_distributions(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(FileDistribution).where(FileDistribution.tenant_id == current_user.tenant_id)
    if status_filter:
        base = base.where(FileDistribution.status == status_filter)
    if search:
        base = base.where(FileDistribution.name.ilike(f"%{search}%"))

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)

    result = await db.execute(
        base.options(selectinload(FileDistribution.targets))
        .order_by(FileDistribution.created_at.desc())
        .offset(offset).limit(limit)
    )
    return {"items": result.scalars().all(), "total": total}


@router.get("/{dist_id}", response_model=FileDistributionRead)
async def get_file_distribution(
    dist_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FileDistribution)
        .options(selectinload(FileDistribution.targets))
        .where(FileDistribution.id == dist_id, FileDistribution.tenant_id == current_user.tenant_id)
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="分发任务不存在")
    return dist


@router.post("/{dist_id}/start", response_model=FileDistributionRead)
async def start_file_distribution(
    dist_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FileDistribution)
        .options(selectinload(FileDistribution.targets))
        .where(FileDistribution.id == dist_id, FileDistribution.tenant_id == current_user.tenant_id)
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="分发任务不存在")
    if dist.status not in ("draft", "failed"):
        raise HTTPException(status_code=400, detail=f"当前状态 {dist.status} 无法启动")

    now = _utcnow()
    dist.status = "pending"
    dist.started_at = now
    for target in dist.targets:
        target.status = "pending"

    # 加速心跳
    agent_ids = [t.agent_id for t in dist.targets]
    configs_result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
    )
    for cfg in configs_result.scalars().all():
        config = dict(cfg.config_json)
        config["heartbeat_override_seconds"] = 10
        cfg.config_json = config
        cfg.config_version = f"v{int(time.time())}"

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "start", "file_distribution", str(dist_id))

    result = await db.execute(
        select(FileDistribution)
        .options(selectinload(FileDistribution.targets))
        .where(FileDistribution.id == dist.id)
    )
    return result.scalar_one()


@router.delete("/{dist_id}", status_code=204)
async def delete_file_distribution(
    dist_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(FileDistribution).where(
            FileDistribution.id == dist_id,
            FileDistribution.tenant_id == current_user.tenant_id,
        )
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="分发任务不存在")
    if dist.status == "running":
        raise HTTPException(status_code=400, detail="运行中的分发任务无法删除")

    # 删除存储文件（校验路径在上传目录内，防止路径遍历删除）
    try:
        p = Path(dist.storage_path).resolve()
        if p.is_file() and p.is_relative_to(UPLOAD_DIR.resolve()):
            p.unlink()
    except OSError:
        pass

    await db.delete(dist)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "delete", "file_distribution", str(dist_id))


@router.get("/{dist_id}/download")
async def download_file(
    dist_id: int,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """Agent 下载文件（需要有效的 download token）"""
    stored_dist_id = _verify_download_token(token)
    if stored_dist_id != dist_id:
        raise HTTPException(status_code=403, detail="无效或已过期的下载令牌")

    result = await db.execute(
        select(FileDistribution).where(FileDistribution.id == dist_id)
    )
    dist = result.scalar_one_or_none()
    if dist is None:
        raise HTTPException(status_code=404, detail="分发任务不存在")

    file_path = Path(dist.storage_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=str(file_path),
        filename=dist.filename,
        media_type="application/octet-stream",
    )


@router.post("/agent/result")
async def agent_submit_distribution_result(
    payload: FileDistributionResultSubmit,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    target_result = await db.execute(
        select(FileDistributionTarget).join(FileDistribution).where(
            FileDistributionTarget.distribution_id == payload.distribution_id,
            FileDistributionTarget.agent_id == agent_context.agent_id,
            FileDistribution.tenant_id == agent_context.tenant_id,
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="未找到对应的分发目标")

    now = _utcnow()
    target.status = payload.status
    target.error_message = payload.error_message
    if payload.status in ("completed", "failed"):
        target.downloaded_at = now

    # 广播结果
    await ws_manager.broadcast(
        agent_context.agent_id,
        {
            "event": "file_distribution_result",
            "distribution_id": payload.distribution_id,
            "agent_id": agent_context.agent_id,
            "status": payload.status,
        },
    )

    # 检查是否所有目标都已完成
    all_targets_result = await db.execute(
        select(FileDistributionTarget).where(FileDistributionTarget.distribution_id == payload.distribution_id)
    )
    all_targets = list(all_targets_result.scalars().all())
    if all(t.status in ("completed", "failed") for t in all_targets):
        dist_result = await db.execute(
            select(FileDistribution).where(FileDistribution.id == payload.distribution_id)
        )
        dist = dist_result.scalar_one_or_none()
        if dist and dist.status in ("pending", "running"):
            has_failed = any(t.status == "failed" for t in all_targets)
            dist.status = "failed" if has_failed else "completed"

            # 发送完成通知
            from ops_platform.scheduler import notify_task_completion
            await notify_task_completion(
                db=db,
                tenant_id=dist.tenant_id,
                task_type="file_distribution",
                task_id=dist.id,
                task_name=dist.name,
                success=not has_failed,
            )

            # 恢复心跳
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
