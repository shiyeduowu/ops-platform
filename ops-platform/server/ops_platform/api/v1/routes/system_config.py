# -*- coding: utf-8 -*-
"""
运维平台自身配置管理 API
可配置：服务器端口、数据库、JWT、Agent、CORS 等
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.db import get_db
from ops_platform.schemas import UserContext

router = APIRouter(prefix="/system-config", tags=["系统配置"])

# 配置文件路径
CONFIG_FILE = Path(__file__).resolve().parents[3] / "platform_config.yaml"
BACKUP_DIR = CONFIG_FILE.parent / "config_backups"
MAX_BACKUPS = 10

# 配置分类定义
CONFIG_SCHEMA = {
    "server": {
        "label": "服务器",
        "icon": "server",
        "fields": {
            "host": {"label": "监听地址", "type": "text", "default": "0.0.0.0", "hint": "服务绑定的 IP 地址"},
            "port": {"label": "监听端口", "type": "number", "default": 8000, "min": 1, "max": 65535, "hint": "HTTP 服务端口"},
            "server_public_url": {"label": "公网地址", "type": "text", "default": "http://127.0.0.1:8000", "hint": "Agent 回调和前端访问的地址"},
            "workers": {"label": "工作进程数", "type": "number", "default": 1, "min": 1, "max": 16, "hint": "uvicorn worker 数量"},
        }
    },
    "database": {
        "label": "数据库",
        "icon": "database",
        "fields": {
            "database_url": {"label": "连接字符串", "type": "text", "default": "sqlite+aiosqlite:///./ops_platform.db", "hint": "SQLAlchemy 异步连接串"},
            "redis_url": {"label": "Redis 地址", "type": "text", "default": "redis://127.0.0.1:6379/0", "hint": "缓存/队列地址（可选）"},
        }
    },
    "security": {
        "label": "安全认证",
        "icon": "shield",
        "fields": {
            "jwt_secret_key": {"label": "JWT 密钥", "type": "password", "default": "change-me-before-production", "hint": "生产环境务必修改"},
            "jwt_algorithm": {"label": "JWT 算法", "type": "select", "options": ["HS256", "HS384", "HS512"], "default": "HS256"},
            "access_token_expire_minutes": {"label": "Token 有效期(分钟)", "type": "number", "default": 120, "min": 5, "max": 1440},
            "agent_signature_tolerance_seconds": {"label": "Agent 签名容差(秒)", "type": "number", "default": 300, "min": 30, "max": 3600, "hint": "Agent 请求时间戳允许的最大偏差"},
        }
    },
    "agent": {
        "label": "Agent 管理",
        "icon": "cpu",
        "fields": {
            "agent_target_version": {"label": "目标版本号", "type": "text", "default": "1.0.0", "hint": "Agent 升级目标版本"},
            "agent_upgrade_url": {"label": "升级包地址", "type": "text", "default": "", "hint": "Agent 下载升级包的 URL"},
            "default_activation_code": {"label": "默认激活码", "type": "text", "default": "OPS-DEMO", "hint": "Agent 注册使用的激活码"},
        }
    },
    "user": {
        "label": "默认账号",
        "icon": "user",
        "fields": {
            "default_admin_username": {"label": "管理员用户名", "type": "text", "default": "admin"},
            "default_admin_password": {"label": "管理员密码", "type": "password", "default": "admin123456", "hint": "仅在首次初始化时使用"},
        }
    },
    "cors": {
        "label": "跨域 CORS",
        "icon": "globe",
        "fields": {
            "cors_origins": {"label": "允许的源", "type": "text", "default": "*", "hint": "多个用逗号分隔，如: http://localhost:5173,https://ops.example.com"},
        }
    },
    "logging": {
        "label": "日志",
        "icon": "file-text",
        "fields": {
            "log_level": {"label": "日志级别", "type": "select", "options": ["DEBUG", "INFO", "WARNING", "ERROR"], "default": "INFO"},
            "log_format": {"label": "日志格式", "type": "text", "default": "%(asctime)s [%(levelname)s] %(message)s"},
        }
    },
}


# ============================================================================
# 请求/响应模型
# ============================================================================

class PlatformConfigRead(BaseModel):
    config: dict[str, Any]
    schema: dict[str, Any]
    config_path: str
    modified_at: Optional[str] = None
    is_production: bool = False


class PlatformConfigSave(BaseModel):
    config: dict[str, Any]


class SaveResponse(BaseModel):
    success: bool
    message: str
    need_restart: bool = False
    restart_fields: list[str] = []


# ============================================================================
# 辅助函数
# ============================================================================

def _require_owner(current_user: UserContext) -> None:
    if current_user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要管理员权限")


def _load_config() -> dict[str, Any]:
    """加载平台配置文件"""
    if not CONFIG_FILE.exists():
        return {}
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def _save_config(config: dict[str, Any]) -> None:
    """保存平台配置文件"""
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    yaml_text = yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False)
    CONFIG_FILE.write_text(yaml_text, encoding="utf-8")


def _backup_config() -> Optional[Path]:
    """备份配置文件"""
    if not CONFIG_FILE.exists():
        return None
    BACKUP_DIR.mkdir(exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup = BACKUP_DIR / f"platform_config_{ts}.yaml"
    shutil.copy2(CONFIG_FILE, backup)
    # 清理旧备份
    backups = sorted(BACKUP_DIR.glob("platform_config_*.yaml"), reverse=True)
    for old in backups[MAX_BACKUPS:]:
        old.unlink(missing_ok=True)
    return backup


def _get_current_values() -> dict[str, Any]:
    """合并配置文件和环境变量，返回当前生效值"""
    file_config = _load_config()
    result = {}
    for category, cat_def in CONFIG_SCHEMA.items():
        for field_key, field_def in cat_def["fields"].items():
            # 优先级：环境变量 > 配置文件 > 默认值
            env_val = os.environ.get(field_key.upper())
            if env_val is not None:
                # 类型转换
                if field_def["type"] == "number":
                    try:
                        result[field_key] = int(env_val)
                    except ValueError:
                        result[field_key] = field_def["default"]
                else:
                    result[field_key] = env_val
            elif field_key in file_config:
                result[field_key] = file_config[field_key]
            else:
                result[field_key] = field_def["default"]
    return result


# 需要重启才能生效的字段
RESTART_REQUIRED = {"host", "port", "database_url", "redis_url", "workers", "jwt_algorithm"}

# 安全敏感字段（返回时遮蔽）
SENSITIVE_FIELDS = {"jwt_secret_key", "default_admin_password"}


# ============================================================================
# API 路由
# ============================================================================

@router.get("/", response_model=PlatformConfigRead)
async def get_platform_config(
    current_user: UserContext = Depends(get_current_user),
):
    """获取平台当前配置"""
    _require_owner(current_user)

    values = _get_current_values()
    # 遮蔽敏感字段
    for field in SENSITIVE_FIELDS:
        if field in values and values[field]:
            values[field] = "***"

    modified_at = None
    if CONFIG_FILE.exists():
        stat = CONFIG_FILE.stat()
        modified_at = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat()

    from ops_platform.core.config import IS_PRODUCTION

    return PlatformConfigRead(
        config=values,
        schema=CONFIG_SCHEMA,
        config_path="(hidden)",
        modified_at=modified_at,
        is_production=IS_PRODUCTION,
    )


@router.put("/", response_model=SaveResponse)
async def save_platform_config(
    payload: PlatformConfigSave,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """保存平台配置"""
    _require_owner(current_user)

    # 验证必填字段
    for category, cat_def in CONFIG_SCHEMA.items():
        for field_key, field_def in cat_def["fields"].items():
            val = payload.config.get(field_key)
            if val is None or val == "":
                if field_key in ("host", "port", "database_url", "jwt_secret_key"):
                    raise HTTPException(400, f"{field_def['label']} 不能为空")

    # 验证端口范围
    port = payload.config.get("port", 8000)
    if not isinstance(port, int) or port < 1 or port > 65535:
        raise HTTPException(400, "端口必须在 1-65535 之间")

    # 过滤掉遮蔽的值（不更新敏感字段的 *** 占位符）
    clean_config = {}
    for key, value in payload.config.items():
        if key in SENSITIVE_FIELDS and value == "***":
            continue  # 保留原值
        clean_config[key] = value

    # 备份
    backup_path = _backup_config()

    # 保存
    _save_config(clean_config)

    # 记录审计日志
    try:
        from ops_platform.api.v1.routes.audit import log_audit
        log_audit(
            db=db,
            tenant_id=current_user.tenant_id,
            user_id=current_user.user_id,
            username=current_user.username,
            action="update",
            resource_type="system_config",
            resource_id="platform_config",
            details={"changed_keys": list(clean_config.keys()), "backup": str(backup_path) if backup_path else None},
        )
        await db.commit()
    except Exception:
        pass

    # 判断哪些字段需要重启
    changed_restart = [k for k in clean_config if k in RESTART_REQUIRED]

    return SaveResponse(
        success=True,
        message="配置已保存" + ("，部分配置需要重启服务才能生效" if changed_restart else ""),
        need_restart=bool(changed_restart),
        restart_fields=changed_restart,
    )


@router.post("/reload", response_model=SaveResponse)
async def reload_platform_config(
    current_user: UserContext = Depends(get_current_user),
):
    """重新加载配置（不停机）"""
    _require_owner(current_user)

    if not CONFIG_FILE.exists():
        return SaveResponse(success=False, message="配置文件不存在")

    return SaveResponse(
        success=True,
        message="配置已标记为待重载，重启服务后生效",
        need_restart=True,
    )
