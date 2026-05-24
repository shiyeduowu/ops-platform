from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    tenant_id: int
    role: str


class LoginRequest(BaseModel):
    username: str = Field(..., max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    tenant_id: int | None = Field(default=None, description="可选，多租户时指定租户")


class UserContext(BaseModel):
    user_id: int
    tenant_id: int
    username: str
    role: str


class TenantCreate(BaseModel):
    name: str = Field(..., max_length=100)
    plan: str = Field(default="free", max_length=20)
    max_agents: int = Field(default=10, ge=0)


class TenantRead(BaseModel):
    id: int
    name: str
    plan: str
    max_agents: int
    created_at: datetime

    class Config:
        from_attributes = True


class ActivationCodeRead(BaseModel):
    id: int
    tenant_id: int
    code: str
    status: str
    max_uses: int
    used_count: int
    expire_at: datetime | None
    created_at: datetime

    class Config:
        from_attributes = True


class LicenseRead(BaseModel):
    id: int
    tenant_id: int
    plan: str
    max_agents: int
    expire_at: datetime | None
    status: str
    feature_flags: dict[str, Any]

    class Config:
        from_attributes = True


class LicenseUpdate(BaseModel):
    plan: str | None = Field(default=None, max_length=20)
    max_agents: int | None = Field(default=None, ge=0)
    expire_at: datetime | None = None
    status: str | None = Field(default=None, max_length=20)
    feature_flags: dict[str, Any] | None = None


class LicenseOverview(BaseModel):
    tenant: TenantRead
    license: LicenseRead | None
    activation_codes: list[ActivationCodeRead]


class AgentRegisterRequest(BaseModel):
    activation_code: str = Field(..., max_length=64)
    hostname: str = Field(..., max_length=100)
    ip: str | None = Field(default=None, max_length=50)
    fingerprint: str | None = Field(default=None, max_length=128)
    version: str = Field(default="unknown", max_length=20)


class AgentRegisterResponse(BaseModel):
    agent_id: str
    secret: str
    server_url: str


class UpgradeInfo(BaseModel):
    need_upgrade: bool = False
    version: str | None = None
    upgrade_url: str | None = None


class HeartbeatPayload(BaseModel):
    agent_id: str = Field(..., max_length=64)
    hostname: str | None = Field(default=None, max_length=100)
    ip: str | None = Field(default=None, max_length=50)
    version: str | None = Field(default=None, max_length=20)
    metrics: dict[str, Any] = Field(default_factory=dict)
    config_version: str = Field(default="v0", max_length=20)


class HeartbeatResponse(BaseModel):
    config_changed: bool
    config: dict[str, Any]
    config_version: str
    upgrade: UpgradeInfo
    server_time: int
    commands: list[StressTestCommand] = Field(default_factory=list)
    remote_commands: list[RemoteCommandItem] = Field(default_factory=list)
    file_distributions: list[FileDistributionItem] = Field(default_factory=list)
    software_deployments: list[SoftwareDeploymentItem] = Field(default_factory=list)


class ConfigRead(BaseModel):
    agent_id: str
    config_json: dict[str, Any]
    config_version: str
    updated_at: datetime

    class Config:
        from_attributes = True


class ConfigUpdate(BaseModel):
    config_json: dict[str, Any]
    config_version: str | None = Field(default=None, max_length=20)


class AgentRead(BaseModel):
    id: int
    tenant_id: int
    agent_id: str
    hostname: str
    ip: str | None
    status: str
    last_seen: datetime | None
    version: str
    last_metrics: dict[str, Any] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class AlertCreate(BaseModel):
    agent_id: str = Field(..., max_length=64)
    type: str = Field(..., max_length=30)
    severity: str = Field(default="warning", max_length=20)
    message: str = Field(..., max_length=2000)
    status: str = Field(default="open", max_length=20)
    details: dict[str, Any] | None = None
    fingerprint: str | None = Field(default=None, max_length=64)


class AlertRead(BaseModel):
    id: int
    tenant_id: int
    agent_id: str
    type: str
    severity: str
    message: str
    status: str
    details: dict[str, Any] | None
    fingerprint: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class LogCreate(BaseModel):
    agent_id: str = Field(..., max_length=64)
    service_key: str = Field(..., max_length=50)
    content: str = Field(..., max_length=10000)
    fingerprint: str | None = Field(default=None, max_length=64)


class LogRead(BaseModel):
    id: int
    agent_id: str
    service_key: str
    content: str
    fingerprint: str
    created_at: datetime

    class Config:
        from_attributes = True


class DashboardSummary(BaseModel):
    total_agents: int
    online_agents: int
    offline_agents: int
    open_alerts: int
    recent_alerts: list[AlertRead]
    agent_list: list[AgentRead]


class AgentAuthContext(BaseModel):
    agent_id: str
    tenant_id: int


# ────────────────────── 压力测试 ──────────────────────


class StressTestCommand(BaseModel):
    """心跳内嵌的压测命令"""
    command_id: str
    test_id: int
    test_type: str
    config: dict[str, Any]
    action: str = "start"


class BrowserStep(BaseModel):
    """浏览器自动化单步操作"""
    action: str = Field(..., description="navigate | click | input | wait | assert_text | screenshot")
    url: str | None = Field(default=None, max_length=2048)
    xpath: str | None = Field(default=None, max_length=1024)
    value: str | None = Field(default=None, max_length=4096)
    timeout_ms: int = Field(default=10000, ge=1000, le=60000)


class StressTestCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    test_type: str = Field(...)
    config: dict[str, Any] = Field(default_factory=dict)
    target_agent_ids: list[str] = Field(..., min_length=1, max_length=50)
    # 调度配置
    is_recurring: bool = False
    schedule_cron: str | None = Field(default=None, max_length=50)
    schedule_interval_seconds: int | None = Field(default=None, ge=60, le=86400)


class StressTestTargetRead(BaseModel):
    id: int
    agent_id: str
    status: str
    command_acked: bool

    class Config:
        from_attributes = True


class StressTestResultRead(BaseModel):
    id: int
    agent_id: str
    status: str
    result_data: dict[str, Any] | None
    error_message: str | None
    started_at: datetime | None
    finished_at: datetime | None

    class Config:
        from_attributes = True


class StressTestRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    test_type: str
    config: dict[str, Any]
    status: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    is_recurring: bool = False
    schedule_cron: str | None = None
    schedule_interval_seconds: int | None = None
    next_run_at: datetime | None = None
    targets: list[StressTestTargetRead] = []
    results: list[StressTestResultRead] = []

    class Config:
        from_attributes = True


class StressTestResultSubmit(BaseModel):
    """Agent 回报压测结果"""
    test_id: int
    status: str = Field(...)
    result_data: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=5000)


# ────────────────────── Agent 分组 ──────────────────────


class AgentGroupCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    color: str = Field(default="#60a5fa", max_length=20)


class AgentGroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = None
    color: str | None = Field(default=None, max_length=20)


class AgentGroupMemberRead(BaseModel):
    agent_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class AgentGroupRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    description: str | None
    color: str
    created_at: datetime
    members: list[AgentGroupMemberRead] = []

    class Config:
        from_attributes = True


# ────────────────────── 远程命令 ──────────────────────


class RemoteCommandCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    command_type: str = Field(..., pattern="^(shell|powershell)$")
    command_text: str = Field(..., min_length=1, max_length=5000)
    timeout_seconds: int = Field(default=60, ge=5, le=300)
    target_agent_ids: list[str] = Field(..., min_length=1, max_length=50)


class RemoteCommandTargetRead(BaseModel):
    id: int
    agent_id: str
    status: str
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None

    class Config:
        from_attributes = True


class RemoteCommandRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    command_type: str
    command_text: str
    timeout_seconds: int
    status: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    targets: list[RemoteCommandTargetRead] = []

    class Config:
        from_attributes = True


class RemoteCommandResultSubmit(BaseModel):
    """Agent 回报命令执行结果"""
    command_id: int
    stdout: str = Field(default="", max_length=100000)
    stderr: str = Field(default="", max_length=100000)
    exit_code: int


class RemoteCommandItem(BaseModel):
    """心跳内嵌的远程命令"""
    command_id: int
    command_type: str
    command_text: str
    timeout_seconds: int = 60


# ────────────────────── 文件分发 ──────────────────────


class FileDistributionRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    filename: str
    target_path: str
    file_size: int
    checksum_md5: str
    status: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    targets: list[FileDistributionTargetRead] = []

    class Config:
        from_attributes = True


class FileDistributionTargetRead(BaseModel):
    id: int
    agent_id: str
    status: str
    downloaded_at: datetime | None
    error_message: str | None

    class Config:
        from_attributes = True


class FileDistributionItem(BaseModel):
    """心跳内嵌的文件分发命令"""
    distribution_id: int
    filename: str
    target_path: str
    file_size: int
    checksum_md5: str
    download_token: str


class FileDistributionResultSubmit(BaseModel):
    """Agent 回报文件下载结果"""
    distribution_id: int
    status: str = Field(...)
    error_message: str | None = Field(default=None, max_length=5000)


# ────────────────────── 软件部署 ──────────────────────


class SoftwareDeploymentTargetRead(BaseModel):
    id: int
    agent_id: str
    file_status: str
    install_status: str
    stdout: str | None
    stderr: str | None
    exit_code: int | None
    started_at: datetime | None
    finished_at: datetime | None

    class Config:
        from_attributes = True


class SoftwareDeploymentRead(BaseModel):
    id: int
    tenant_id: int
    name: str
    software_name: str
    version: str
    installer_filename: str
    file_size: int
    install_command: str
    install_args: str | None
    timeout_seconds: int
    status: str
    created_by: str
    created_at: datetime
    started_at: datetime | None
    targets: list[SoftwareDeploymentTargetRead] = []

    class Config:
        from_attributes = True


class SoftwareDeploymentItem(BaseModel):
    """心跳内嵌的软件部署命令"""
    deployment_id: int
    installer_filename: str
    install_command: str
    install_args: str | None
    timeout_seconds: int
    download_token: str


class SoftwareDeploymentResultSubmit(BaseModel):
    """Agent 回报部署结果"""
    deployment_id: int
    phase: str = Field(..., pattern="^(file|install)$")
    status: str = Field(...)
    stdout: str | None = Field(default=None, max_length=100000)
    stderr: str | None = Field(default=None, max_length=100000)
    exit_code: int | None = None
    error_message: str | None = Field(default=None, max_length=5000)
