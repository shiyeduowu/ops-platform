from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    JSON,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


BigIntPk = BigInteger().with_variant(Integer, "sqlite")
JsonDocument = JSON().with_variant(JSONB(), "postgresql")


def _utcnow() -> datetime:
    """返回当前UTC时间（替代已弃用的datetime.utcnow）"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    max_agents: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    users: Mapped[list["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    agents: Mapped[list["Agent"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    alerts: Mapped[list["Alert"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    licenses: Mapped[list["License"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")
    activation_codes: Mapped[list["ActivationCode"]] = relationship(
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    notification_channels: Mapped[list["NotificationChannel"]] = relationship(
        cascade="all, delete-orphan",
    )


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("tenant_id", "username", name="uq_users_tenant_username"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="users")


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agents_agent_id"),
        Index("idx_agents_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    hostname: Mapped[str] = mapped_column(String(100), nullable=False)
    ip: Mapped[str | None] = mapped_column(String(50), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="offline", nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    secret_key: Mapped[str] = mapped_column(Text, nullable=False)
    version: Mapped[str] = mapped_column(String(20), default="unknown", nullable=False)
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    last_metrics: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="agents")
    config: Mapped["AgentConfig"] = relationship(
        back_populates="agent",
        cascade="all, delete-orphan",
        uselist=False,
    )


class AgentConfig(Base):
    __tablename__ = "agent_configs"
    __table_args__ = (
        UniqueConstraint("agent_id", name="uq_agent_configs_agent_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agents.agent_id", ondelete="CASCADE"),
        nullable=False,
    )
    config_json: Mapped[dict] = mapped_column(JsonDocument, default=dict, nullable=False)
    config_version: Mapped[str] = mapped_column(String(20), default="v1", nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)

    agent: Mapped["Agent"] = relationship(back_populates="config")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("idx_alerts_tenant_created", "tenant_id", "created_at"),
        Index("idx_alerts_agent_created", "agent_id", "created_at"),
        Index("idx_alerts_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), default="warning", nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    details: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="alerts")


class Log(Base):
    __tablename__ = "logs"
    __table_args__ = (
        Index("idx_logs_agent_created", "agent_id", "created_at"),
        Index("idx_logs_fingerprint", "fingerprint"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    service_key: Mapped[str] = mapped_column(String(50), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class License(Base):
    __tablename__ = "licenses"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    plan: Mapped[str] = mapped_column(String(20), default="free", nullable=False)
    max_agents: Mapped[int] = mapped_column(Integer, default=10, nullable=False)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    feature_flags: Mapped[dict] = mapped_column(JsonDocument, default=dict, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="licenses")


class ActivationCode(Base):
    __tablename__ = "activation_codes"
    __table_args__ = (
        UniqueConstraint("code", name="uq_activation_codes_code"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    max_uses: Mapped[int] = mapped_column(Integer, default=1000, nullable=False)
    used_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    expire_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="activation_codes")


class NotificationChannel(Base):
    """通知渠道配置"""
    __tablename__ = "notification_channels"
    __table_args__ = (
        Index("idx_nc_tenant_enabled", "tenant_id", "enabled"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)  # dingtalk/wecom/feishu/email/webhook
    config: Mapped[dict] = mapped_column(JsonDocument, nullable=False)  # 渠道配置（webhook_url等）
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    tenant: Mapped["Tenant"] = relationship(back_populates="notification_channels")


class AuditLog(Base):
    """审计日志"""
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index("idx_audit_tenant_created", "tenant_id", "created_at"),
        Index("idx_audit_user_created", "user_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(nullable=False)
    username: Mapped[str] = mapped_column(String(50), nullable=False)
    action: Mapped[str] = mapped_column(String(50), nullable=False)  # login/create/update/delete
    resource_type: Mapped[str] = mapped_column(String(50), nullable=False)  # agent/config/alert/channel
    resource_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    details: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class MetricHistory(Base):
    """指标历史数据"""
    __tablename__ = "metric_history"
    __table_args__ = (
        Index("idx_metric_agent_time", "agent_id", "recorded_at"),
        Index("idx_metric_tenant_time", "tenant_id", "recorded_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tenant_id: Mapped[int] = mapped_column(nullable=False, index=True)
    metrics: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class AlertForwardingLog(Base):
    """告警转发记录 — 持久化每次通知发送的结果"""
    __tablename__ = "alert_forwarding_logs"
    __table_args__ = (
        Index("idx_afl_tenant_created", "tenant_id", "created_at"),
        Index("idx_afl_alert_id", "alert_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    alert_id: Mapped[int | None] = mapped_column(nullable=True)
    channel_id: Mapped[int] = mapped_column(nullable=False)
    channel_name: Mapped[str] = mapped_column(String(50), nullable=False)
    channel_type: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)  # success / failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)


class StressTest(Base):
    """压力测试任务"""
    __tablename__ = "stress_tests"
    __table_args__ = (
        Index("idx_stress_tests_tenant_status", "tenant_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    test_type: Mapped[str] = mapped_column(String(30), nullable=False)
    config: Mapped[dict] = mapped_column(JsonDocument, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 调度字段
    is_recurring: Mapped[bool] = mapped_column(default=False, nullable=False)
    schedule_cron: Mapped[str | None] = mapped_column(String(50), nullable=True)
    schedule_interval_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    targets: Mapped[list["StressTestTarget"]] = relationship(
        back_populates="test", cascade="all, delete-orphan",
    )
    results: Mapped[list["StressTestResult"]] = relationship(
        back_populates="test", cascade="all, delete-orphan",
    )


class StressTestTarget(Base):
    """压力测试目标 Agent"""
    __tablename__ = "stress_test_targets"
    __table_args__ = (
        UniqueConstraint("test_id", "agent_id", name="uq_stress_test_target"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(
        ForeignKey("stress_tests.id", ondelete="CASCADE"), index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    command_acked: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    test: Mapped["StressTest"] = relationship(back_populates="targets")


class StressTestResult(Base):
    """压力测试结果（每个 Agent 一条）"""
    __tablename__ = "stress_test_results"
    __table_args__ = (
        Index("idx_stress_results_test_agent", "test_id", "agent_id"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    test_id: Mapped[int] = mapped_column(
        ForeignKey("stress_tests.id", ondelete="CASCADE"), index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    result_data: Mapped[dict | None] = mapped_column(JsonDocument, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    test: Mapped["StressTest"] = relationship(back_populates="results")


class AgentGroup(Base):
    """Agent 分组"""
    __tablename__ = "agent_groups"

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str] = mapped_column(String(20), default="#60a5fa", nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    members: Mapped[list["AgentGroupMember"]] = relationship(
        back_populates="group", cascade="all, delete-orphan",
    )


class AgentGroupMember(Base):
    """分组成员"""
    __tablename__ = "agent_group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "agent_id", name="uq_group_member"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("agent_groups.id", ondelete="CASCADE"), index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)

    group: Mapped["AgentGroup"] = relationship(back_populates="members")


class RemoteCommand(Base):
    """远程命令"""
    __tablename__ = "remote_commands"
    __table_args__ = (
        Index("idx_rc_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    command_type: Mapped[str] = mapped_column(String(20), nullable=False)  # shell / powershell
    command_text: Mapped[str] = mapped_column(Text, nullable=False)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=60, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    targets: Mapped[list["RemoteCommandTarget"]] = relationship(
        back_populates="command", cascade="all, delete-orphan",
    )


class RemoteCommandTarget(Base):
    """远程命令执行目标"""
    __tablename__ = "remote_command_targets"
    __table_args__ = (
        UniqueConstraint("command_id", "agent_id", name="uq_rc_target"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    command_id: Mapped[int] = mapped_column(
        ForeignKey("remote_commands.id", ondelete="CASCADE"), index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    command: Mapped["RemoteCommand"] = relationship(back_populates="targets")


class FileDistribution(Base):
    """文件分发任务"""
    __tablename__ = "file_distributions"
    __table_args__ = (
        Index("idx_fd_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    target_path: Mapped[str] = mapped_column(String(500), nullable=False)  # Agent 端存放路径
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum_md5: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    targets: Mapped[list["FileDistributionTarget"]] = relationship(
        back_populates="distribution", cascade="all, delete-orphan",
    )


class FileDistributionTarget(Base):
    """文件分发目标"""
    __tablename__ = "file_distribution_targets"
    __table_args__ = (
        UniqueConstraint("distribution_id", "agent_id", name="uq_fd_target"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    distribution_id: Mapped[int] = mapped_column(
        ForeignKey("file_distributions.id", ondelete="CASCADE"), index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    downloaded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    distribution: Mapped["FileDistribution"] = relationship(back_populates="targets")


class SoftwareDeployment(Base):
    """软件部署任务"""
    __tablename__ = "software_deployments"
    __table_args__ = (
        Index("idx_sd_tenant_created", "tenant_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    software_name: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    installer_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    storage_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(BigInteger, default=0, nullable=False)
    checksum_md5: Mapped[str] = mapped_column(String(32), nullable=False)
    install_command: Mapped[str] = mapped_column(Text, nullable=False)  # 安装命令模板
    install_args: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[int] = mapped_column(Integer, default=300, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    created_by: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    targets: Mapped[list["SoftwareDeploymentTarget"]] = relationship(
        back_populates="deployment", cascade="all, delete-orphan",
    )


class SoftwareDeploymentTarget(Base):
    """软件部署目标"""
    __tablename__ = "software_deployment_targets"
    __table_args__ = (
        UniqueConstraint("deployment_id", "agent_id", name="uq_sd_target"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    deployment_id: Mapped[int] = mapped_column(
        ForeignKey("software_deployments.id", ondelete="CASCADE"), index=True,
    )
    agent_id: Mapped[str] = mapped_column(String(64), nullable=False)
    file_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    install_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    stdout: Mapped[str | None] = mapped_column(Text, nullable=True)
    stderr: Mapped[str | None] = mapped_column(Text, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    deployment: Mapped["SoftwareDeployment"] = relationship(back_populates="targets")


class AiopsConfig(Base):
    """Per-tenant AI 运维配置"""
    __tablename__ = "aiops_configs"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_aiops_config_tenant"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)
    model_override: Mapped[str | None] = mapped_column(String(100), nullable=True)  # 租户可自定义模型
    config_json: Mapped[dict] = mapped_column(JsonDocument, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, onupdate=_utcnow)


class KnowledgeDocument(Base):
    """知识库文档元数据（RAG）"""
    __tablename__ = "knowledge_documents"
    __table_args__ = (
        Index("idx_kd_tenant_source", "tenant_id", "source_type"),
    )

    id: Mapped[int] = mapped_column(BigIntPk, primary_key=True, autoincrement=True)
    tenant_id: Mapped[int] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)  # manual/alert/inspection/script
    source_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    embedding_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending/done/failed
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_utcnow, nullable=False)
