from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError as JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.core.security import decode_access_token, verify_agent_signature
from ops_platform.db import get_db
from ops_platform.models import Agent, User
from ops_platform.schemas import AgentAuthContext, UserContext


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> UserContext:
    if credentials is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    try:
        payload = decode_access_token(credentials.credentials)
    except JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token") from None

    user_id = int(payload.get("sub", 0))
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="user not found")
    return UserContext(
        user_id=user.id,
        tenant_id=user.tenant_id,
        username=user.username,
        role=user.role,
    )


async def get_agent_context(
    x_agent_id: str = Header(..., alias="X-Agent-ID"),
    x_agent_signature: str = Header(..., alias="X-Agent-Signature"),
    x_agent_timestamp: int = Header(..., alias="X-Agent-Timestamp"),
    db: AsyncSession = Depends(get_db),
) -> AgentAuthContext:
    result = await db.execute(select(Agent).where(Agent.agent_id == x_agent_id))
    agent = result.scalar_one_or_none()
    if agent is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown agent")
    if not verify_agent_signature(agent.secret_key, x_agent_id, x_agent_timestamp, x_agent_signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid agent signature")
    return AgentAuthContext(agent_id=agent.agent_id, tenant_id=agent.tenant_id)

