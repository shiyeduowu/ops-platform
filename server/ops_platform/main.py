from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import func, select

from ops_platform.api.v1.router import api_router
from ops_platform.api.ws import router as websocket_router
from ops_platform.core.config import settings, IS_PRODUCTION
from ops_platform.core.security import hash_password
from ops_platform.db import AsyncSessionLocal, init_db
from ops_platform.models import ActivationCode, License, Tenant, User  # noqa: F401
# 确保所有模型在 create_all 前已导入
import ops_platform.models  # noqa: F401


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ops-platform")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """添加安全响应头"""

    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Content-Security-Policy"] = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self' ws: wss:;"
        if IS_PRODUCTION:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


async def seed_defaults() -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(func.count()).select_from(Tenant))
        tenant_count = int(result.scalar() or 0)
        if tenant_count > 0:
            return

        tenant = Tenant(name="Default", plan="enterprise", max_agents=100)
        db.add(tenant)
        await db.flush()

        admin = User(
            tenant_id=tenant.id,
            username=settings.default_admin_username,
            password_hash=hash_password(settings.default_admin_password),
            role="owner",
        )
        license_row = License(
            tenant_id=tenant.id,
            plan="enterprise",
            max_agents=100,
            expire_at=datetime.now(timezone.utc) + timedelta(days=3650),
            status="active",
            feature_flags={"logs": True, "alerts": True, "websocket": True},
        )
        activation = ActivationCode(
            tenant_id=tenant.id,
            code=settings.default_activation_code,
            status="active",
            max_uses=1000,
        )
        db.add_all([admin, license_row, activation])
        await db.commit()
        logger.info(
            "Seeded default tenant, admin user '%s'",
            settings.default_admin_username,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    await init_db()
    await seed_defaults()

    # 启动后台巡检任务
    from ops_platform.scheduler import patrol_loop
    task = asyncio.create_task(patrol_loop())
    logger.info("后台巡检任务已启动")

    yield

    # 停止巡检任务
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    logger.info("后台巡检任务已停止")


app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    description="Commercial distributed ops SaaS control plane",
    lifespan=lifespan,
)

# 使用配置中的 CORS 白名单（通配符源不能与 credentials 同时使用）
_allow_credentials = settings.cors_origins != ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 安全响应头
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/health")
async def health():
    return {"status": "ok", "timestamp": int(time.time())}


app.include_router(api_router, prefix="/api/v1")
app.include_router(websocket_router)


STATIC_DIR = Path(__file__).resolve().parents[1] / "static"
if (STATIC_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")


@app.get("/", include_in_schema=False)
@app.get("/{full_path:path}", include_in_schema=False)
async def serve_console(full_path: str = ""):
    if full_path.startswith(("api/", "ws/")):
        raise HTTPException(status_code=404, detail="not found")
    if STATIC_DIR.is_dir():
        target = (STATIC_DIR / full_path).resolve()
        # 路径遍历防护：使用 is_relative_to 避免 Windows 路径分隔符绕过
        if not target.is_relative_to(STATIC_DIR.resolve()):
            raise HTTPException(status_code=404, detail="not found")
        if target.is_file():
            return FileResponse(target)
        index = STATIC_DIR / "index.html"
        if index.is_file():
            return FileResponse(index)
    return {
        "status": "backend-ready",
        "console": "run frontend build to serve the web console from this process",
    }
