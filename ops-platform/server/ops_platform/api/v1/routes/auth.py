from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.api.v1.routes.audit import log_audit
from ops_platform.core.config import settings
from ops_platform.core.security import create_access_token, verify_password
from ops_platform.db import get_db
from ops_platform.models import User
from ops_platform.schemas import LoginRequest, TokenResponse, UserContext


router = APIRouter(prefix="/auth", tags=["auth"])

# 简易登录限流：每个 IP 5分钟内最多 10 次失败尝试
_login_attempts: dict[str, list[float]] = defaultdict(list)
_rate_lock = Lock()
_MAX_ATTEMPTS = 10
_WINDOW_SECONDS = 300
_last_cleanup = time.time()


def _check_rate_limit(ip: str) -> None:
    global _last_cleanup
    now = time.time()
    with _rate_lock:
        # 定期清理过期条目，防止内存无限增长
        if now - _last_cleanup > 60:
            cutoff = now - _WINDOW_SECONDS
            expired_ips = [k for k, v in _login_attempts.items() if not v or v[-1] < cutoff]
            for k in expired_ips:
                del _login_attempts[k]
            _last_cleanup = now

        attempts = _login_attempts[ip]
        _login_attempts[ip] = [t for t in attempts if now - t < _WINDOW_SECONDS]
        if len(_login_attempts[ip]) >= _MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="登录尝试过于频繁，请稍后再试",
            )


def _record_failure(ip: str) -> None:
    with _rate_lock:
        _login_attempts[ip].append(time.time())


def _token_for_user(user: User) -> TokenResponse:
    token = create_access_token(
        subject=str(user.id),
        claims={"tenant_id": user.tenant_id, "role": user.role},
    )
    return TokenResponse(
        access_token=token,
        expires_in=settings.access_token_expire_minutes * 60,
        tenant_id=user.tenant_id,
        role=user.role,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    client_ip = request.client.host if request.client else "unknown"
    _check_rate_limit(client_ip)

    query = select(User).where(User.username == payload.username)
    if payload.tenant_id is not None:
        query = query.where(User.tenant_id == payload.tenant_id)
    result = await db.execute(query)
    user = result.scalars().first()
    if user is None or not verify_password(payload.password, user.password_hash):
        _record_failure(client_ip)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid username or password")
    await log_audit(db, user.tenant_id, user.id, user.username, "login", "auth", details={"username": payload.username}, ip_address=client_ip)
    return _token_for_user(user)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == current_user.user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return _token_for_user(user)

