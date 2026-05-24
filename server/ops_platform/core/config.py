from __future__ import annotations

import os
import sys
import logging
import secrets
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 检测是否为生产环境
IS_PRODUCTION = os.getenv("ENV", "development").lower() in ("production", "prod")


def _require_env_or_warn(key: str, default: str, is_secret: bool = False) -> str:
    """要求环境变量或发出警告"""
    value = os.getenv(key, default)

    if value == default:
        if IS_PRODUCTION:
            if is_secret:
                logger.critical(
                    f"安全警告: 生产环境必须设置 {key} 环境变量！"
                )
                sys.exit(1)
            else:
                logger.warning(f"警告: {key} 使用默认值，建议在生产环境设置环境变量")
        else:
            if is_secret:
                logger.warning(f"开发模式: {key} 使用默认值，生产环境请设置环境变量")

    return value


def _require_env_or_generate(key: str, is_secret: bool = True) -> str:
    """要求环境变量，未设置时自动生成随机值（仅限非生产环境）"""
    value = os.getenv(key)
    if value:
        return value
    if IS_PRODUCTION:
        logger.critical(f"安全警告: 生产环境必须设置 {key} 环境变量！")
        sys.exit(1)
    generated = secrets.token_urlsafe(48)
    logger.warning(f"开发模式: {key} 未设置，已自动生成随机值")
    return generated


@dataclass(frozen=True)
class Settings:
    app_name: str = "Ops Platform"
    api_version: str = "v1"

    database_url: str = field(default_factory=lambda: _require_env_or_warn(
        "DATABASE_URL",
        "sqlite+aiosqlite:///./ops_platform.db"
    ))

    redis_url: str = field(default_factory=lambda: os.getenv(
        "REDIS_URL",
        "redis://127.0.0.1:6379/0"
    ))

    server_public_url: str = field(default_factory=lambda: os.getenv(
        "SERVER_PUBLIC_URL",
        "http://127.0.0.1:8000"
    ))

    # 生产环境必须设置这些值
    default_activation_code: str = field(default_factory=lambda: _require_env_or_generate(
        "DEFAULT_ACTIVATION_CODE",
    ))

    default_admin_username: str = field(default_factory=lambda: _require_env_or_warn(
        "DEFAULT_ADMIN_USERNAME",
        "admin"
    ))

    default_admin_password: str = field(default_factory=lambda: _require_env_or_generate(
        "DEFAULT_ADMIN_PASSWORD",
    ))

    jwt_secret_key: str = field(default_factory=lambda: _require_env_or_generate(
        "JWT_SECRET_KEY",
    ))

    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = field(default_factory=lambda: int(
        os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "120")
    ))
    agent_signature_tolerance_seconds: int = field(default_factory=lambda: int(
        os.getenv("AGENT_SIGNATURE_TOLERANCE_SECONDS", "300")
    ))
    agent_target_version: str = field(default_factory=lambda: os.getenv(
        "AGENT_TARGET_VERSION",
        "1.0.0"
    ))
    agent_upgrade_url: str | None = field(default_factory=lambda: os.getenv(
        "AGENT_UPGRADE_URL"
    ))

    # CORS 白名单（生产环境必须设置）
    cors_origins: list[str] = field(default_factory=lambda: _parse_cors_origins())

    # AIOps 配置（实际由 modules/aiops/config.py 管理，此处仅作文档占位）
    # 相关环境变量: AIOPS_ENABLED, AIOPS_API_KEY, AIOPS_BASE_URL, AIOPS_MODEL


def _parse_cors_origins() -> list[str]:
    """解析 CORS 源白名单"""
    origins_str = os.getenv("CORS_ORIGINS", "")
    if origins_str:
        return [o.strip() for o in origins_str.split(",") if o.strip()]

    if IS_PRODUCTION:
        logger.warning("生产环境未设置 CORS_ORIGINS，使用默认 localhost")
        return ["http://localhost:5173", "http://localhost:8000"]
    else:
        # 开发环境允许所有源
        return ["*"]


settings = Settings()

# 启动时打印配置摘要
if not IS_PRODUCTION:
    logger.info("=" * 50)
    logger.info("运行模式: 开发环境")
    logger.info("数据库: %s", settings.database_url.split("///")[-1] if "///" in settings.database_url else settings.database_url)
    logger.info("JWT密钥: %s", "***已自动生成***" if not os.getenv("JWT_SECRET_KEY") else "***已从环境变量读取***")
    logger.info("CORS: %s", "允许所有源" if settings.cors_origins == ["*"] else str(settings.cors_origins))
    logger.info("=" * 50)
