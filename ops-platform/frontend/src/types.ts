export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  tenant_id: number;
  role: string;
}

export interface Tenant {
  id: number;
  name: string;
  plan: string;
  max_agents: number;
  created_at: string;
}

export interface Agent {
  id: number;
  tenant_id: number;
  agent_id: string;
  hostname: string;
  ip: string | null;
  status: string;
  last_seen: string | null;
  version: string;
  last_metrics?: Record<string, unknown> | null;
  created_at: string;
}

export interface AlertItem {
  id: number;
  tenant_id: number;
  agent_id: string;
  type: string;
  severity: string;
  message: string;
  status: string;
  details: Record<string, unknown> | null;
  fingerprint: string | null;
  created_at: string;
}

export interface LogItem {
  id: number;
  agent_id: string;
  service_key: string;
  content: string;
  fingerprint: string;
  created_at: string;
}

export interface DashboardSummary {
  total_agents: number;
  online_agents: number;
  offline_agents: number;
  open_alerts: number;
  recent_alerts: AlertItem[];
  agent_list: Agent[];
}

export interface AgentConfig {
  agent_id: string;
  config_json: Record<string, unknown>;
  config_version: string;
  updated_at: string;
}

export interface AgentConfigFieldSchema {
  label: string;
  type: string;
  hint?: string;
  default?: any;
  min?: number;
  max?: number;
  unit?: string;
  fields?: Record<string, { label: string; type: string; placeholder?: string; default?: any }>;
}

export type AgentConfigSchema = Record<string, AgentConfigFieldSchema>;

export interface ActivationCode {
  id: number;
  tenant_id: number;
  code: string;
  status: string;
  max_uses: number;
  used_count: number;
  expire_at: string | null;
  created_at: string;
}

export interface License {
  id: number;
  tenant_id: number;
  plan: string;
  max_agents: number;
  expire_at: string | null;
  status: string;
  feature_flags: Record<string, unknown>;
}

export interface LicenseOverview {
  tenant: Tenant;
  license: License | null;
  activation_codes: ActivationCode[];
}

export interface WsEvent {
  event: "metrics" | "log" | "alert" | "config" | string;
  agent_id: string;
  metrics?: Record<string, unknown>;
  log?: LogItem;
  alert?: AlertItem;
  config_version?: string;
  server_time?: number;
}

export interface NotificationChannel {
  id: number;
  name: string;
  channel_type: string;
  config: Record<string, unknown>;
  enabled: boolean;
}

export interface AuditLogItem {
  id: number;
  user_id: number;
  username: string;
  action: string;
  resource_type: string;
  resource_id: string | null;
  details: Record<string, unknown> | null;
  ip_address: string | null;
  created_at: string;
}

export interface AuditStats {
  total: number;
  today: number;
  by_action: Record<string, number>;
  by_resource: Record<string, number>;
}

export interface LogSearchResult {
  total: number;
  keyword: string;
  logs: {
    id: number;
    agent_id: string;
    service_key: string;
    content: string;
    highlighted_content: string;
    fingerprint: string;
    created_at: string | null;
  }[];
}

export interface LogStats {
  total: number;
  hours: number;
  by_service: Record<string, number>;
  top_agents: Record<string, number>;
}

export interface SystemConfigFile {
  filename: string;
  label: string;
  modified_at: string | null;
  size_bytes: number;
}

export interface SystemConfigContent {
  filename: string;
  label: string;
  yaml_text: string;
  data: Record<string, unknown>;
  modified_at: string | null;
}

export interface SystemConfigSaveResponse {
  success: boolean;
  message: string;
  backup_path: string | null;
}

export interface PlatformConfigField {
  label: string;
  type: "text" | "password" | "number" | "select";
  default: any;
  hint?: string;
  min?: number;
  max?: number;
  options?: string[];
}

export interface PlatformConfigCategory {
  label: string;
  icon: string;
  fields: Record<string, PlatformConfigField>;
}

export type PlatformConfigSchema = Record<string, PlatformConfigCategory>;

export interface PlatformConfig {
  config: Record<string, any>;
  schema: PlatformConfigSchema;
  config_path: string;
  modified_at: string | null;
  is_production: boolean;
}

export interface PlatformConfigSaveResponse {
  success: boolean;
  message: string;
  need_restart: boolean;
  restart_fields: string[];
}

export interface ForwardingLog {
  id: number;
  alert_id: number | null;
  channel_id: number;
  channel_name: string;
  channel_type: string;
  status: string;
  error_message: string | null;
  created_at: string;
}

// ────────────── 压力测试 ──────────────

export interface StressTestTarget {
  id: number;
  agent_id: string;
  status: string;
  command_acked: boolean;
}

export interface StressTestResult {
  id: number;
  agent_id: string;
  status: string;
  result_data: Record<string, any> | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface StressTest {
  id: number;
  tenant_id: number;
  name: string;
  test_type: string;
  config: Record<string, any>;
  status: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  is_recurring: boolean;
  schedule_cron: string | null;
  schedule_interval_seconds: number | null;
  next_run_at: string | null;
  targets: StressTestTarget[];
  results: StressTestResult[];
}

export interface BrowserStep {
  action: string;
  url?: string;
  xpath?: string;
  value?: string;
  timeout_ms?: number;
}

// ────────────── Agent 分组 ──────────────

export interface AgentGroupMember {
  agent_id: string;
  created_at: string;
}

export interface AgentGroup {
  id: number;
  tenant_id: number;
  name: string;
  description: string | null;
  color: string;
  created_at: string;
  members: AgentGroupMember[];
}

// ────────────── 远程命令 ──────────────

export interface RemoteCommandTarget {
  id: number;
  agent_id: string;
  status: string;
  stdout: string | null;
  stderr: string | null;
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface RemoteCommand {
  id: number;
  tenant_id: number;
  name: string;
  command_type: string;
  command_text: string;
  timeout_seconds: number;
  status: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  targets: RemoteCommandTarget[];
}

// ────────────── 文件分发 ──────────────

export interface FileDistributionTarget {
  id: number;
  agent_id: string;
  status: string;
  downloaded_at: string | null;
  error_message: string | null;
}

export interface FileDistribution {
  id: number;
  tenant_id: number;
  name: string;
  filename: string;
  target_path: string;
  file_size: number;
  checksum_md5: string;
  status: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  targets: FileDistributionTarget[];
}

// ────────────── 软件部署 ──────────────

export interface SoftwareDeploymentTarget {
  id: number;
  agent_id: string;
  file_status: string;
  install_status: string;
  stdout: string | null;
  stderr: string | null;
  exit_code: number | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface SoftwareDeployment {
  id: number;
  tenant_id: number;
  name: string;
  software_name: string;
  version: string;
  installer_filename: string;
  file_size: number;
  install_command: string;
  install_args: string | null;
  timeout_seconds: number;
  status: string;
  created_by: string;
  created_at: string;
  started_at: string | null;
  targets: SoftwareDeploymentTarget[];
}

