from __future__ import annotations

import ipaddress
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from ops_platform.api.deps import get_agent_context, get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.db import get_db
from ops_platform.models import Agent, AgentConfig, StressTest, StressTestTarget, StressTestResult
from ops_platform.schemas import (
    AgentAuthContext,
    PaginatedResponse,
    StressTestCommand,
    StressTestCreate,
    StressTestRead,
    StressTestResultSubmit,
    UserContext,
)
from ops_platform.websocket import ws_manager


router = APIRouter(prefix="/stress-tests", tags=["stress-tests"])

INFRA_TYPES = {
    "network_bandwidth", "network_latency", "network_packet_loss",
    "disk_io", "cpu_stress", "memory_stress",
}
ALL_TYPES = INFRA_TYPES | {"browser_automation", "http_api"}

ALLOWED_BROWSER_SCHEMES = {"http", "https"}
BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}


def _validate_browser_url(url: str) -> None:
    if not url:
        raise HTTPException(status_code=400, detail="URL 不能为空")
    try:
        parsed = urlparse(url)
    except Exception:
        raise HTTPException(status_code=400, detail="URL 格式无效")
    if parsed.scheme not in ALLOWED_BROWSER_SCHEMES:
        raise HTTPException(status_code=400, detail="仅支持 http/https 协议")
    hostname = (parsed.hostname or "").lower()
    if hostname in BLOCKED_HOSTNAMES:
        raise HTTPException(status_code=400, detail="禁止访问本机地址")
    try:
        ip = ipaddress.ip_address(hostname)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            raise HTTPException(status_code=400, detail="禁止访问私有/保留 IP 地址")
    except ValueError:
        pass


def _validate_test_config(test_type: str, config: dict[str, Any]) -> None:
    if test_type not in ALL_TYPES:
        raise HTTPException(status_code=400, detail=f"无效的测试类型: {test_type}")
    if test_type in {"network_bandwidth", "network_latency", "network_packet_loss"}:
        target = config.get("target_host", "")
        if not target:
            raise HTTPException(status_code=400, detail="网络测试必须指定 target_host")
    if test_type == "browser_automation":
        steps = config.get("steps", [])
        if not steps:
            raise HTTPException(status_code=400, detail="浏览器测试至少需要一个步骤")
        valid_actions = {"navigate", "click", "input", "wait", "assert_text", "screenshot"}
        for i, step in enumerate(steps):
            action = step.get("action", "")
            if action not in valid_actions:
                raise HTTPException(status_code=400, detail=f"步骤 {i+1} 无效操作: {action}")
            if step.get("url"):
                _validate_browser_url(step["url"])
            xpath = step.get("xpath", "")
            if xpath and ("script" in xpath.lower() or "javascript:" in xpath.lower()):
                raise HTTPException(status_code=400, detail=f"步骤 {i+1} xpath 包含危险模式")

    if test_type == "http_api":
        targets = config.get("targets", [])
        if not targets:
            raise HTTPException(status_code=400, detail="HTTP API 测试至少需要一个目标")
        for i, t in enumerate(targets):
            if not t.get("url"):
                raise HTTPException(status_code=400, detail=f"目标 {i+1} 缺少 url")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.post("", response_model=StressTestRead, status_code=201)
async def create_stress_test(
    payload: StressTestCreate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _validate_test_config(payload.test_type, payload.config)

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

    now = _utcnow()
    next_run = None
    if payload.is_recurring and payload.schedule_interval_seconds:
        from datetime import timedelta
        next_run = now + timedelta(seconds=payload.schedule_interval_seconds)

    test = StressTest(
        tenant_id=current_user.tenant_id,
        name=payload.name,
        test_type=payload.test_type,
        config=payload.config,
        status="draft",
        created_by=current_user.username,
        is_recurring=payload.is_recurring,
        schedule_cron=payload.schedule_cron,
        schedule_interval_seconds=payload.schedule_interval_seconds,
        next_run_at=next_run,
    )
    db.add(test)
    await db.flush()

    for agent_id in payload.target_agent_ids:
        db.add(StressTestTarget(test_id=test.id, agent_id=agent_id))

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "create", "stress_test", str(test.id))

    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test.id)
    )
    return result.scalar_one()


@router.get("", response_model=PaginatedResponse[StressTestRead])
async def list_stress_tests(
    status_filter: str | None = Query(default=None, alias="status"),
    test_type: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import func
    base = select(StressTest).where(StressTest.tenant_id == current_user.tenant_id)
    if status_filter:
        base = base.where(StressTest.status == status_filter)
    if test_type:
        base = base.where(StressTest.test_type == test_type)
    if search:
        base = base.where(StressTest.name.ilike(f"%{search}%"))

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = int(count_result.scalar() or 0)

    result = await db.execute(
        base.options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .order_by(StressTest.created_at.desc())
        .offset(offset).limit(limit)
    )
    return {"items": result.scalars().all(), "total": total}


@router.get("/{test_id}", response_model=StressTestRead)
async def get_stress_test(
    test_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test_id, StressTest.tenant_id == current_user.tenant_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="测试不存在")
    return test


@router.post("/{test_id}/start", response_model=StressTestRead)
async def start_stress_test(
    test_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test_id, StressTest.tenant_id == current_user.tenant_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="测试不存在")
    if test.status not in ("draft", "failed"):
        raise HTTPException(status_code=400, detail=f"当前状态 {test.status} 无法启动")

    now = _utcnow()
    test.status = "pending"
    test.started_at = now
    for target in test.targets:
        target.status = "pending"
        target.command_acked = False

    # 通过配置推送临时加速心跳间隔，让 Agent 更快拉取命令
    agent_ids = [t.agent_id for t in test.targets]
    configs_result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
    )
    for cfg in configs_result.scalars().all():
        config = dict(cfg.config_json)
        config["heartbeat_override_seconds"] = 10
        cfg.config_json = config
        cfg.config_version = f"v{int(time.time())}"

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "start", "stress_test", str(test_id))

    # 重新加载关系
    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test.id)
    )
    return result.scalar_one()


@router.post("/{test_id}/cancel", response_model=StressTestRead)
async def cancel_stress_test(
    test_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test_id, StressTest.tenant_id == current_user.tenant_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="测试不存在")
    if test.status not in ("pending", "running"):
        raise HTTPException(status_code=400, detail=f"当前状态 {test.status} 无法取消")

    test.status = "cancelled"
    test.finished_at = _utcnow()
    for target in test.targets:
        if target.status in ("pending", "running"):
            target.status = "cancelled"

    # 恢复心跳间隔
    agent_ids = [t.agent_id for t in test.targets]
    configs_result = await db.execute(
        select(AgentConfig).where(AgentConfig.agent_id.in_(agent_ids))
    )
    for cfg in configs_result.scalars().all():
        config = dict(cfg.config_json)
        config.pop("heartbeat_override_seconds", None)
        cfg.config_json = config
        cfg.config_version = f"v{int(time.time())}"

    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "cancel", "stress_test", str(test_id))

    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test.id)
    )
    return result.scalar_one()


@router.delete("/{test_id}", status_code=204)
async def delete_stress_test(
    test_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StressTest).where(
            StressTest.id == test_id,
            StressTest.tenant_id == current_user.tenant_id,
        )
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="测试不存在")
    if test.status == "running":
        raise HTTPException(status_code=400, detail="运行中的测试无法删除，请先取消")

    await db.delete(test)
    await db.commit()
    await log_audit(db, current_user.tenant_id, current_user.user_id, current_user.username, "delete", "stress_test", str(test_id))


@router.get("/{test_id}/results", response_model=list[StressTestRead])
async def get_stress_test_results(
    test_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test_id, StressTest.tenant_id == current_user.tenant_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="测试不存在")
    return [test]


@router.get("/{test_id}/report")
async def get_stress_test_report(
    test_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(StressTest)
        .options(selectinload(StressTest.targets), selectinload(StressTest.results))
        .where(StressTest.id == test_id, StressTest.tenant_id == current_user.tenant_id)
    )
    test = result.scalar_one_or_none()
    if test is None:
        raise HTTPException(status_code=404, detail="测试不存在")

    # 聚合各 Agent 结果
    per_agent = []
    total_requests = 0
    total_success = 0
    total_errors = 0
    all_latencies = []

    for r in test.results:
        data = r.result_data or {}
        agent_info = {
            "agent_id": r.agent_id,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "error_message": r.error_message,
        }

        if test.test_type == "http_api":
            # HTTP API 结果
            summary = data.get("summary", {})
            agent_info.update({
                "total_requests": summary.get("total_requests", 0),
                "total_success": summary.get("total_success", 0),
                "overall_qps": summary.get("overall_qps", 0),
                "duration_seconds": summary.get("duration_seconds", 0),
            })
            total_requests += summary.get("total_requests", 0)
            total_success += summary.get("total_success", 0)
            total_errors += summary.get("total_errors", 0)
        elif test.test_type in INFRA_TYPES:
            # 基础设施结果
            agent_info.update({
                "metrics": data.get("metrics", {}),
                "summary": data.get("summary", ""),
            })
            if "cpu_percent" in data:
                agent_info["cpu_peak"] = data.get("cpu_percent", 0)
            if "iterations" in data:
                agent_info["iterations"] = data.get("iterations", 0)
        else:
            agent_info["data"] = data

        per_agent.append(agent_info)

    # 计算持续时间
    duration_seconds = None
    if test.started_at and test.finished_at:
        duration_seconds = (test.finished_at - test.started_at).total_seconds()

    report = {
        "test_id": test.id,
        "test_name": test.name,
        "test_type": test.test_type,
        "status": test.status,
        "created_by": test.created_by,
        "created_at": test.created_at.isoformat(),
        "started_at": test.started_at.isoformat() if test.started_at else None,
        "finished_at": test.finished_at.isoformat() if test.finished_at else None,
        "duration_seconds": duration_seconds,
        "agents_count": len(test.targets),
        "config": test.config,
        "per_agent": per_agent,
        "summary": {
            "total_requests": total_requests,
            "total_success": total_success,
            "total_errors": total_errors,
            "overall_success_rate": round(total_success / max(total_requests, 1) * 100, 1),
        },
    }

    return report


@router.post("/agent/result")
async def agent_submit_result(
    payload: StressTestResultSubmit,
    agent_context: AgentAuthContext = Depends(get_agent_context),
    db: AsyncSession = Depends(get_db),
):
    # 验证该 Agent 是此测试的目标
    target_result = await db.execute(
        select(StressTestTarget).join(StressTest).where(
            StressTestTarget.test_id == payload.test_id,
            StressTestTarget.agent_id == agent_context.agent_id,
            StressTest.tenant_id == agent_context.tenant_id,
        )
    )
    target = target_result.scalar_one_or_none()
    if target is None:
        raise HTTPException(status_code=404, detail="未找到对应的测试目标")

    # 查找或创建结果记录
    result_row = await db.execute(
        select(StressTestResult).where(
            StressTestResult.test_id == payload.test_id,
            StressTestResult.agent_id == agent_context.agent_id,
        )
    )
    existing = result_row.scalar_one_or_none()

    now = _utcnow()
    is_terminal = payload.status in ("completed", "failed")

    if existing:
        existing.status = payload.status
        existing.result_data = payload.result_data
        existing.error_message = payload.error_message
        if is_terminal:
            existing.finished_at = now
    else:
        db.add(StressTestResult(
            test_id=payload.test_id,
            agent_id=agent_context.agent_id,
            status=payload.status,
            result_data=payload.result_data,
            error_message=payload.error_message,
            started_at=now,
            finished_at=now if is_terminal else None,
        ))

    if is_terminal:
        target.status = payload.status

    await db.commit()

    # 广播结果到前端
    await ws_manager.broadcast(
        agent_context.agent_id,
        {
            "event": "stress_test_result",
            "test_id": payload.test_id,
            "agent_id": agent_context.agent_id,
            "status": payload.status,
            "result_data": payload.result_data,
            "error_message": payload.error_message,
        },
    )

    # 如果包含监控数据，单独广播 monitor 事件
    if payload.result_data and "monitor" in payload.result_data:
        await ws_manager.broadcast(
            agent_context.agent_id,
            {
                "event": "stress_test_monitor",
                "test_id": payload.test_id,
                "agent_id": agent_context.agent_id,
                "metrics": payload.result_data["monitor"],
            },
        )

    # 检查是否所有目标都已完成
    all_targets_result = await db.execute(
        select(StressTestTarget).where(StressTestTarget.test_id == payload.test_id)
    )
    all_targets = list(all_targets_result.scalars().all())
    if all(t.status in ("completed", "failed", "cancelled") for t in all_targets):
        test_result = await db.execute(
            select(StressTest).where(StressTest.id == payload.test_id)
        )
        test = test_result.scalar_one_or_none()
        if test and test.status in ("pending", "running"):
            has_failed = any(t.status == "failed" for t in all_targets)
            test.status = "failed" if has_failed else "completed"
            test.finished_at = now

            # 发送完成通知
            from ops_platform.scheduler import notify_task_completion
            await notify_task_completion(
                db=db,
                tenant_id=test.tenant_id,
                task_type="stress_test",
                task_id=test.id,
                task_name=test.name,
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
