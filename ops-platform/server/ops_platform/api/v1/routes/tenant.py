from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.db import get_db
from ops_platform.models import Tenant
from ops_platform.schemas import TenantRead, UserContext


router = APIRouter(prefix="/tenant", tags=["tenant"])


@router.get("/me", response_model=TenantRead)
async def get_current_tenant(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")
    return tenant

