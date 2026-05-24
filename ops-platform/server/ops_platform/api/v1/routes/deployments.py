from __future__ import annotations

import hashlib
import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.db import get_db
from ops_platform.models import Agent, AgentConfig, SoftwareDeployment, SoftwareDeploymentTarget
from ops_platform.schemas import (
    AgentAuthContext,
    PaginatedResponse,
    SoftwareDeploymentRead,
    SoftwareDeploymentResultSubmit,
    UserContext,
)
from ops_platform.websocket import ws_manager


router = APIRouter(prefix="/deployments", tags=["deployments"])

# 使用绝对路径
UPLOAD_DIR = Path(__file__).resolve().parents[4] / "uploads" / "deployments"
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB
TOKEN_TTL_SECONDS = 3600

# 允许的安装命令前缀
ALLOWED_INSTALLERS = {
    "msiexec", "msiexec.exe",
    "setup", "setup.exe", "install", "install.exe",
    "dpkg", "apt", "apt-get", "yum", "rpm",
    "pip", "pip3", "python", "python3",
}

_SHELL_META = re.compile(r"[;|&$`\n\r]")

_download_tokens: dict[str, tuple[int, float]] = {}


def _generate_download_token(deployment_id: int) -> str:
    token = uuid.uuid4().hex
    _download_tokens[token] = (deployment_id, time.time())
    return token


def _verify_download_token(token: str) -> int | None:
    entry = _download_tokens.pop(token, None)
    if entry is None:
        return None
    dist_id, created_at = entry
    if time.time() - created_at > TOKEN_TTL_SECONDS:
        return None
    return dist_id


def _validate_install_command(command: str) -> None:
    """校验安装命令安全性"""
    if not command.strip():
        raise HTTPException(status_code=400, detail="安装命令不能为空")
    if _SHELL_META.search(command):
        raise HTTPException(status_code=400, detail="安装命令包含不允许的特殊字符（;|&$` 等）")
    first = command.strip().split()[0].lower()
    if "/" in first:
        first = first.rsplit("/", 1)[-1]
    if "\\" in first:
        first = first.rsplit("\\", 1)[-1]
    if first not in ALLOWED_INSTALLERS:
        raise HTTPException(
            status_code=400,
            detail=f"不允许的安装程序: {first}。允许: {', '.join(sorted(ALLOWED_INSTALLERS))}",
        )


def _sanitize_filename(filename: str) -> str:
    name = Path(filename).name
    name = re.sub(r"[^\w\-.]", "_", name)
    return name or "installer"


def _compute_md5(file_path: Path) -> str:
    h = hashlib.md5()
    with open(file_path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", response_model=SoftwareDeploymentRead, status_code=201)
async def create_deployment(
    name: str = Form(...),
    software_name: str = Form(...),
    version: str = Form(...),
    install_command: str = Form(...),
    install_args: str = Form(default=""),
    timeout_seconds: int = Form(default=300),
    target_agent_ids: str = Form(...),
    file: UploadFile = File(...),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        agent_ids = json.loads(target_agent_ids)
        if not isinstance(agent_ids, list) or not agent_ids:
            raise ValueError
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="target_agent_ids 格式无效")

    content = await file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail=f"文件大小超过限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）")
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件不能为空")

    _validate_install_command(install_command)
    if install_args and _SHELL_META.search(install_args):
        raise HTTPException(status_code=400, detail="安装参数包含不允许的特殊字符")

    # 验证 Agent
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
    filename = _sanitize_filename(file.filename or "installer")
    storage_name = f"{uuid.uuid4().hex}_{filename}"
    storage_path = UPLOAD_DIR / storage_name
    storage_path.write_bytes(content)
    md5 = _compute_md5(storage_path)

    deployment = SoftwareDeployment(
        tenant_id=current_user.tenant_id,
        name=name,
        software_name=software_name,
        version=version,
        installer_filename=filename,
        storage_path=str(storage_path),
        file_size=len(content),
        checksum_md5=md5,
        install_command=install_command,
        install_args=install_args or None,
        timeout_seconds=timeout_seconds,
        status="draft",
        created_by=current_user.username,
    )
    db.add(deployment)
    await db.flush()

    for agent_id in agent_ids:
        db.add(SoftwareDeploymentTarget(deployment_id=deployment.id, agent_id=agent_id))

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "create", "deployment", str(deployment.id))

    result = await db.execute(
        select(SoftwareDeployment)
        .options(selectinload(SoftwareDeployment.targets))
        .where(SoftwareDeployment.id == deployment.id)
    )
    return result.scalar_one()


@router.get("", response_model=PaginatedResponse[SoftwareDeploymentRead])
async def list_deployments(
    search: str | None = Query(default=None),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(SoftwareDeployment).where(SoftwareDeployment.tenant_id == current_user.tenant_id)
    if status_filter:
        base = base.where(SoftwareDeployment.status == status_filter)
    if search:
        base = base.where(SoftwareDeployment.name.ilike(f"%{search}%"))

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)

    result = await db.execute(
        base.options(selectinload(SoftwareDeployment.targets))
        .order_by(SoftwareDeployment.created_at.desc())
        .offset(offset).limit(limit)
    )
    return {"items": result.scalars().all(), "total": total}


@router.get("/{deployment_id}", response_model=SoftwareDeploymentRead)
async def get_deployment(
    deployment_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SoftwareDeployment)
        .options(selectinload(SoftwareDeployment.targets))
        .where(SoftwareDeployment.id == deployment_id, SoftwareDeployment.tenant_id == current_user.tenant_id)
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=404, detail="部署任务不存在")
    return dep


@router.post("/{deployment_id}/start", response_model=SoftwareDeploymentRead)
async def start_deployment(
    deployment_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SoftwareDeployment)
        .options(selectinload(SoftwareDeployment.targets))
        .where(SoftwareDeployment.id == deployment_id, SoftwareDeployment.tenant_id == current_user.tenant_id)
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=404, detail="部署任务不存在")
    if dep.status not in ("draft", "failed"):
        raise HTTPException(status_code=400, detail=f"当前状态 {dep.status} 无法启动")

    now = _utcnow()
    dep.status = "pending"
    dep.started_at = now
    for t in dep.targets:
        t.file_status = "pending"
        t.install_status = "pending"

    # 加速心跳
    agent_ids = [t.agent_id for t in dep.targets]
    configs_result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
    )
    for cfg in configs_result.scalars().all():
        config = dict(cfg.config_json)
        config["heartbeat_override_seconds"] = 10
        cfg.config_json = config
        cfg.config_version = f"v{int(time.time())}"

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "start", "deployment", str(deployment_id))

    result = await db.execute(
        select(SoftwareDeployment)
        .options(selectinload(SoftwareDeployment.targets))
        .where(SoftwareDeployment.id == dep.id)
    )
    return result.scalar_one()


@router.delete("/{deployment_id}", status_code=204)
async def delete_deployment(
    deployment_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(SoftwareDeployment).where(
            SoftwareDeployment.id == deployment_id,
            SoftwareDeployment.tenant_id == current_user.tenant_id,
        )
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=404, detail="部署任务不存在")
    if dep.status == "running":
        raise HTTPException(status_code=400, detail="运行中的部署任务无法删除")

    try:
        p = Path(dep.storage_path).resolve()
        if p.is_file() and p.is_relative_to(UPLOAD_DIR.resolve()):
            p.unlink()
    except OSError:
        pass

    await db.delete(dep)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "delete", "deployment", str(deployment_id))


@router.get("/{deployment_id}/download")
async def download_installer(
    deployment_id: int,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    stored_id = _verify_download_token(token)
    if stored_id != deployment_id:
        raise HTTPException(status_code=403, detail="无效或已过期的下载令牌")

    result = await db.execute(
        select(SoftwareDeployment).where(SoftwareDeployment.id == deployment_id)
    )
    dep = result.scalar_one_or_none()
    if dep is None:
        raise HTTPException(status_code=404, detail="部署任务不存在")

    file_path = Path(dep.storage_path)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="安装包不存在")

    from fastapi.responses import FileResponse
    return FileResponse(
        path=str(file_path),
        filename=dep.installer_filename,
        media_type="application/octet-stream",
    )


@router.post("/agent/result")
async def agent_submit_deployment_result(
    payload: SoftwareDeploymentResultSubmit,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    target_result = await db.execute(
        select(SoftwareDeploymentTarget).join(SoftwareDeployment).where(
            SoftwareDeploymentTarget.deployment_id == payload.deployment_id,
            SoftwareDeploymentTarget.agent_id == agent_context.agent_id,
            SoftwareDeployment.tenant_id == agent_context.tenant_id,
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="未找到对应的部署目标")

    now = _utcnow()

    if payload.phase == "file":
        target.file_status = payload.status
        if payload.status == "failed":
            target.install_status = "skipped"
            target.finished_at = now
            target.error_message = payload.error_message
    elif payload.phase == "install":
        target.install_status = payload.status
        target.stdout = (payload.stdout or "")[:100000]
        target.stderr = (payload.stderr or "")[:100000]
        target.exit_code = payload.exit_code
        if payload.status in ("completed", "failed"):
            target.finished_at = now

    # 广播
    await ws_manager.broadcast(
        agent_context.agent_id,
        {
            "event": "deployment_result",
            "deployment_id": payload.deployment_id,
            "agent_id": agent_context.agent_id,
            "phase": payload.phase,
            "status": payload.status,
        },
    )

    # 检查是否所有目标完成
    all_targets_result = await db.execute(
        select(SoftwareDeploymentTarget).where(SoftwareDeploymentTarget.deployment_id == payload.deployment_id)
    )
    all_targets = list(all_targets_result.scalars().all())
    all_done = all(
        (t.file_status in ("completed", "failed") and t.install_status in ("completed", "failed", "skipped"))
        for t in all_targets
    )
    if all_done:
        dep_result = await db.execute(
            select(SoftwareDeployment).where(SoftwareDeployment.id == payload.deployment_id)
        )
        dep = dep_result.scalar_one_or_none()
        if dep and dep.status in ("pending", "running"):
            has_failed = any(t.install_status == "failed" or t.file_status == "failed" for t in all_targets)
            dep.status = "failed" if has_failed else "completed"

            # 发送完成通知
            from ops_platform.scheduler import notify_task_completion
            await notify_task_completion(
                db=db,
                tenant_id=dep.tenant_id,
                task_type="software_deployment",
                task_id=dep.id,
                task_name=dep.name,
                success=not has_failed,
            )

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
