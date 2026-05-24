from __future__ import annotations

from fastapi import APIRouter

from ops_platform.api.v1.routes import agents, alerts, auth, configs, license, logs, stress_tests, system_config, tenant, template, notifications, audit, agent_groups, remote_commands, file_distributions, deployments
from ops_platform.api.v1.routes import aiops


api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(tenant.router)
api_router.include_router(license.router)
api_router.include_router(agents.router)
api_router.include_router(configs.router)
api_router.include_router(alerts.router)
api_router.include_router(logs.router)
api_router.include_router(template.router)
api_router.include_router(notifications.router)
api_router.include_router(audit.router)
api_router.include_router(system_config.router)
api_router.include_router(stress_tests.router)
api_router.include_router(agent_groups.router)
api_router.include_router(remote_commands.router)
api_router.include_router(file_distributions.router)
api_router.include_router(deployments.router)
api_router.include_router(aiops.router)
