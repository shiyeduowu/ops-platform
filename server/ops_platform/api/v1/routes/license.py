from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_platform.api.deps import get_current_user
from ops_platform.db import get_db
from ops_platform.models import ActivationCode, License, Tenant
from ops_platform.schemas import LicenseOverview, LicenseRead, LicenseUpdate, UserContext


router = APIRouter(prefix="/license", tags=["license"])


def _require_owner(current_user: UserContext) -> None:
    if current_user.role not in {"owner", "admin"}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="owner role required")


async def _load_latest_license(db: AsyncSession, tenant_id: int) -> License | None:
    result = await db.execute(
        select(License)
        .where(License.tenant_id == tenant_id)
        .order_by(License.id.desc())
    )
    return result.scalars().first()


@router.get("/me", response_model=LicenseOverview)
async def get_license_overview(
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="tenant not found")

    license_row = await _load_latest_license(db, current_user.tenant_id)
    codes_result = await db.execute(
        select(ActivationCode)
        .where(ActivationCode.tenant_id == current_user.tenant_id)
        .order_by(ActivationCode.created_at.desc())
    )
    return LicenseOverview(
        tenant=tenant,
        license=license_row,
        activation_codes=list(codes_result.scalars().all()),
    )


@router.put("/me", response_model=LicenseRead)
async def update_license(
    payload: LicenseUpdate,
    current_user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    _require_owner(current_user)
    license_row = await _load_latest_license(db, current_user.tenant_id)
    if license_row is None:
        license_row = License(
            tenant_id=current_user.tenant_id,
            plan=payload.plan or "free",
            max_agents=payload.max_agents if payload.max_agents is not None else 10,
            expire_at=payload.expire_at,
            status=payload.status or "active",
            feature_flags=payload.feature_flags or {},
        )
        db.add(license_row)
    else:
        for field, value in payload.model_dump(exclude_unset=True).items():
            setattr(license_row, field, value)

    tenant_result = await db.execute(select(Tenant).where(Tenant.id == current_user.tenant_id))
    tenant = tenant_result.scalar_one_or_none()
    if tenant is not None:
        tenant.plan = license_row.plan
        tenant.max_agents = license_row.max_agents

    await db.commit()
    await db.refresh(license_row)
    return license_row
