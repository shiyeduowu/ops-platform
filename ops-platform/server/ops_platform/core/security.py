from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt as pyjwt
from passlib.context import CryptContext

from ops_platform.core.config import settings


password_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


def create_access_token(subject: str, claims: dict[str, Any] | None = None) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": subject,
        "exp": expires_at,
        "iat": datetime.now(timezone.utc),
    }
    if claims:
        payload.update(claims)
    return pyjwt.encode(payload, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    return pyjwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])


def generate_agent_secret() -> str:
    return secrets.token_urlsafe(48)


def sign_agent_request(secret_key: str, agent_id: str, timestamp: int) -> str:
    message = f"{agent_id}.{timestamp}".encode("utf-8")
    return hmac.new(secret_key.encode("utf-8"), message, hashlib.sha256).hexdigest()


def verify_agent_signature(secret_key: str, agent_id: str, timestamp: int, signature: str) -> bool:
    drift = abs(int(time.time()) - timestamp)
    if drift > settings.agent_signature_tolerance_seconds:
        return False
    expected = sign_agent_request(secret_key, agent_id, timestamp)
    return hmac.compare_digest(expected, signature)


def stable_agent_id(seed: str) -> str:
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
