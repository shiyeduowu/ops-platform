CREATE TABLE IF NOT EXISTS tenants (
    id BIGSERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    plan VARCHAR(20) NOT NULL DEFAULT 'free',
    max_agents INT NOT NULL DEFAULT 10,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS users (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    username VARCHAR(50) NOT NULL,
    password_hash TEXT NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'owner',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_users_tenant_username UNIQUE (tenant_id, username)
);

CREATE TABLE IF NOT EXISTS agents (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id VARCHAR(64) NOT NULL UNIQUE,
    hostname VARCHAR(100) NOT NULL,
    ip VARCHAR(50),
    status VARCHAR(20) NOT NULL DEFAULT 'offline',
    last_seen TIMESTAMP,
    secret_key TEXT NOT NULL,
    version VARCHAR(20) NOT NULL DEFAULT 'unknown',
    fingerprint VARCHAR(128),
    last_metrics JSONB,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS agent_configs (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(64) NOT NULL UNIQUE REFERENCES agents(agent_id) ON DELETE CASCADE,
    config_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    config_version VARCHAR(20) NOT NULL DEFAULT 'v1',
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS alerts (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    agent_id VARCHAR(64) NOT NULL,
    type VARCHAR(30) NOT NULL,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',
    message TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'open',
    details JSONB,
    fingerprint VARCHAR(64),
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS logs (
    id BIGSERIAL PRIMARY KEY,
    agent_id VARCHAR(64) NOT NULL,
    service_key VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    fingerprint VARCHAR(64) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS licenses (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    plan VARCHAR(20) NOT NULL DEFAULT 'free',
    max_agents INT NOT NULL DEFAULT 10,
    expire_at TIMESTAMP,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    feature_flags JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS activation_codes (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    code VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    max_uses INT NOT NULL DEFAULT 1000,
    used_count INT NOT NULL DEFAULT 0,
    expire_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agents_tenant_status ON agents(tenant_id, status);
CREATE INDEX IF NOT EXISTS idx_agents_fingerprint ON agents(fingerprint);
CREATE INDEX IF NOT EXISTS idx_alerts_tenant_created ON alerts(tenant_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_alerts_agent_created ON alerts(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_agent_created ON logs(agent_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_logs_fingerprint ON logs(fingerprint);
