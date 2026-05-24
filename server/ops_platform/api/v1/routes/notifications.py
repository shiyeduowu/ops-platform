# -*- coding: utf-8 -*-
"""
通知渠道管理 API
"""

from __future__ import annotations

from typing import Optional

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.db import get_db
from ops_platform.models import AlertForwardingLog, NotificationChannel
from ops_platform.schemas import UserContext


router = APIRouter(prefix="/notifications", tags=["通知渠道"])


# ============================================================================
# 请求/响应模型
# ============================================================================

class ChannelCreate(BaseModel):
    name: str
    channel_type: str  # dingtalk/wecom/feishu/email/webhook
    config: dict
    enabled: bool = True

    @property
    def name_stripped(self) -> str:
        return self.name.strip()[:50]


class ChannelUpdate(BaseModel):
    name: Optional[str] = None
    config: Optional[dict] = None
    enabled: Optional[bool] = None


class ChannelRead(BaseModel):
    id: int
    name: str
    channel_type: str
    config: dict
    enabled: bool

    class Config:
        from_attributes = True

    @classmethod
    def from_orm_masked(cls, obj):
        """遮蔽敏感配置字段"""
        data = {
            "id": obj.id,
            "name": obj.name,
            "channel_type": obj.channel_type,
            "config": dict(obj.config) if obj.config else {},
            "enabled": obj.enabled,
        }
        sensitive_keys = {"password", "secret", "token", "authorization"}
        for key in list(data["config"].keys()):
            if key.lower() in sensitive_keys:
                data["config"][key] = "***"
        return cls(**data)


class ChannelTest(BaseModel):
    message: str = "这是一条测试通知"


class ForwardingLogRead(BaseModel):
    id: int
    alert_id: int | None
    channel_id: int
    channel_name: str
    channel_type: str
    status: str
    error_message: str | None
    created_at: datetime

    class Config:
        from_attributes = True


# ============================================================================
# API 路由
# ============================================================================

def _mask_config(config: dict) -> dict:
    """遮蔽敏感配置字段"""
    masked = dict(config)
    sensitive_keys = {"password", "secret", "token", "authorization"}
    for key in list(masked.keys()):
        if key.lower() in sensitive_keys:
            masked[key] = "***"
    return masked


@router.get("/", response_model=list[ChannelRead])
async def list_channels(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取所有通知渠道"""
    result = await db.execute(
        select(NotificationChannel)
        .where(NotificationChannel.tenant_id == current_user.tenant_id)
        .order_by(NotificationChannel.created_at.desc())
    )
    channels = result.scalars().all()
    return [
        ChannelRead(
            id=ch.id, name=ch.name, channel_type=ch.channel_type,
            config=_mask_config(ch.config), enabled=ch.enabled,
        )
        for ch in channels
    ]


@router.post("/", response_model=ChannelRead, status_code=201)
async def create_channel(
    payload: ChannelCreate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """创建通知渠道"""
    # 验证渠道类型
    valid_types = {"dingtalk", "wecom", "feishu", "email", "webhook", "custom_http"}
    if payload.channel_type not in valid_types:
        raise HTTPException(400, f"不支持的渠道类型，可选: {valid_types}")

    # 输入验证
    name = payload.name.strip()[:50]
    if not name:
        raise HTTPException(400, "渠道名称不能为空")

    # 验证配置
    _validate_config(payload.channel_type, payload.config)

    channel = NotificationChannel(
        tenant_id=current_user.tenant_id,
        name=name,
        channel_type=payload.channel_type,
        config=payload.config,
        enabled=payload.enabled,
    )
    db.add(channel)
    await db.commit()
    await db.refresh(channel)
    return ChannelRead(
        id=channel.id, name=channel.name, channel_type=channel.channel_type,
        config=_mask_config(channel.config), enabled=channel.enabled,
    )


# 注意: /forwarding-logs 和 /schema 等固定路径必须在 /{channel_id} 之前声明，否则会被通配路由拦截

@router.get("/forwarding-logs", response_model=list[ForwardingLogRead])
async def list_forwarding_logs(
    hours: int = Query(default=24, ge=1, le=168),
    status_filter: str | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """查询告警转发记录"""
    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = (
        select(AlertForwardingLog)
        .where(
            AlertForwardingLog.tenant_id == current_user.tenant_id,
            AlertForwardingLog.created_at >= since,
        )
    )
    if status_filter:
        query = query.where(AlertForwardingLog.status == status_filter)
    result = await db.execute(query.order_by(AlertForwardingLog.created_at.desc()).limit(limit))
    return result.scalars().all()


@router.get("/{channel_id}", response_model=ChannelRead)
async def get_channel(
    channel_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """获取单个通知渠道"""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == current_user.tenant_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(404, "通知渠道不存在")
    return ChannelRead(
        id=channel.id, name=channel.name, channel_type=channel.channel_type,
        config=_mask_config(channel.config), enabled=channel.enabled,
    )


@router.put("/{channel_id}", response_model=ChannelRead)
async def update_channel(
    channel_id: int,
    payload: ChannelUpdate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """更新通知渠道"""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == current_user.tenant_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(404, "通知渠道不存在")

    if payload.name is not None:
        channel.name = payload.name
    if payload.config is not None:
        _validate_config(channel.channel_type, payload.config)
        channel.config = payload.config
    if payload.enabled is not None:
        channel.enabled = payload.enabled

    await db.commit()
    await db.refresh(channel)
    return ChannelRead(
        id=channel.id, name=channel.name, channel_type=channel.channel_type,
        config=_mask_config(channel.config), enabled=channel.enabled,
    )


@router.delete("/{channel_id}")
async def delete_channel(
    channel_id: int,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """删除通知渠道"""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == current_user.tenant_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(404, "通知渠道不存在")

    await db.delete(channel)
    await db.commit()
    return {"success": True}


@router.post("/{channel_id}/test")
async def test_channel(
    channel_id: int,
    payload: ChannelTest,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """测试通知渠道"""
    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.id == channel_id,
            NotificationChannel.tenant_id == current_user.tenant_id,
        )
    )
    channel = result.scalar_one_or_none()
    if not channel:
        raise HTTPException(404, "通知渠道不存在")

    from ops_platform.notifier import create_channel, format_alert_message

    notifier = create_channel(channel.channel_type, channel.config)
    if not notifier:
        raise HTTPException(500, "创建通知渠道失败")

    title, content = format_alert_message({
        "type": "测试告警",
        "severity": "info",
        "hostname": "测试主机",
        "agent_id": "test-agent",
        "message": payload.message,
    })

    success = notifier.send(title, content)
    if success:
        return {"success": True, "message": "测试通知发送成功"}
    else:
        raise HTTPException(500, "测试通知发送失败")


# ============================================================================
# 辅助函数
# ============================================================================

def _validate_webhook_url(url: str) -> None:
    """验证 webhook URL 安全性，阻止 SSRF 攻击"""
    if not url:
        raise HTTPException(400, "webhook_url 不能为空")
    if not url.startswith(("https://", "http://")):
        raise HTTPException(400, "webhook_url 必须以 http:// 或 https:// 开头")
    from urllib.parse import urlparse
    import ipaddress
    import socket
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        # 尝试解析为 IP 地址
        try:
            ip = ipaddress.ip_address(hostname)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                raise HTTPException(400, "不允许使用内网/保留地址")
        except ValueError:
            # hostname 是域名，解析 DNS 并检查解析结果
            if hostname in ("localhost",):
                raise HTTPException(400, "不允许使用内网地址")
            try:
                resolved_ips = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC)
                for _, _, _, _, sockaddr in resolved_ips:
                    ip = ipaddress.ip_address(sockaddr[0])
                    if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                        raise HTTPException(400, f"域名解析到内网地址，不允许使用")
            except socket.gaierror:
                raise HTTPException(400, "域名解析失败")
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(400, "webhook_url 格式无效")


def _validate_config(channel_type: str, config: dict):
    """验证渠道配置"""
    if channel_type in ("dingtalk", "wecom", "feishu"):
        if "webhook_url" not in config:
            raise HTTPException(400, f"{channel_type} 需要 webhook_url 配置")
        _validate_webhook_url(config["webhook_url"])
    elif channel_type == "email":
        required = ["smtp_host", "username", "password"]
        for key in required:
            if key not in config:
                raise HTTPException(400, f"邮件渠道需要 {key} 配置")
        # 验证 SMTP 端口
        port = config.get("smtp_port", 587)
        if not isinstance(port, int) or port < 1 or port > 65535:
            raise HTTPException(400, "smtp_port 必须是 1-65535 之间的整数")
    elif channel_type == "webhook":
        if "webhook_url" not in config:
            raise HTTPException(400, "webhook 需要 webhook_url 配置")
        _validate_webhook_url(config["webhook_url"])
    elif channel_type == "custom_http":
        if "url" not in config:
            raise HTTPException(400, "自定义 HTTP 通道需要 url 配置")
        _validate_webhook_url(config["url"])
        method = config.get("method", "POST")
        if method not in ("GET", "POST", "PUT", "PATCH"):
            raise HTTPException(400, "method 必须是 GET/POST/PUT/PATCH")
        if "headers" in config and not isinstance(config["headers"], dict):
            raise HTTPException(400, "headers 必须是字典类型")
        body_template = config.get("body_template")
        if body_template is not None:
            if not isinstance(body_template, str) or len(body_template) > 10000:
                raise HTTPException(400, "body_template 必须是字符串且不超过 10000 字符")
        timeout = config.get("timeout", 15)
        if not isinstance(timeout, int) or timeout < 5 or timeout > 60:
            raise HTTPException(400, "timeout 必须是 5-60 之间的整数")


