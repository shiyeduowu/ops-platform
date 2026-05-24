import type {
  Agent,
  AgentConfig,
  AgentConfigSchema,
  AgentGroup,
  AlertItem,
  AuditLogItem,
  AuditStats,
  DashboardSummary,
  FileDistribution,
  ForwardingLog,
  LicenseOverview,
  LogItem,
  LogSearchResult,
  LogStats,
  NotificationChannel,
  PlatformConfig,
  PlatformConfigSaveResponse,
  RemoteCommand,
  SoftwareDeployment,
  StressTest,
  SystemConfigContent,
  SystemConfigFile,
  SystemConfigSaveResponse,
  Tenant,
  TokenResponse
} from "./types";

const TOKEN_KEY = "ops-platform-token";
const ROLE_KEY = "ops-platform-role";

export function getApiBase(): string {
  const envBase = import.meta.env.VITE_API_BASE_URL as string | undefined;
  if (envBase) return envBase.replace(/\/$/, "");
  if (["5173", "5174", "5175"].includes(window.location.port)) return "http://127.0.0.1:8000";
  return window.location.origin;
}

export function getWsBase(): string {
  const envBase = import.meta.env.VITE_WS_BASE_URL as string | undefined;
  if (envBase) return envBase.replace(/\/$/, "");
  const apiBase = getApiBase();
  return apiBase.replace(/^https:/, "wss:").replace(/^http:/, "ws:");
}

export function getToken(): string {
  return localStorage.getItem(TOKEN_KEY) || "";
}

export function isAuthenticated(): boolean {
  return Boolean(getToken());
}

export function saveSession(token: TokenResponse): void {
  localStorage.setItem(TOKEN_KEY, token.access_token);
  localStorage.setItem(ROLE_KEY, token.role);
}

export function clearSession(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ROLE_KEY);
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers);
  if (!headers.has("Content-Type") && options.body) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const response = await fetch(`${getApiBase()}${path}`, {
    ...options,
    headers
  });

  if (response.status === 401) {
    clearSession();
    window.location.href = "/login";
    throw new Error("未授权");
  }
  if (!response.ok) {
    let message = `HTTP ${response.status}`;
    try {
      const body = await response.json();
      message = body.detail || message;
    } catch {
      message = response.statusText || message;
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export const api = {
  login(username: string, password: string) {
    return request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password })
    });
  },
  tenant() {
    return request<Tenant>("/api/v1/tenant/me");
  },
  license() {
    return request<LicenseOverview>("/api/v1/license/me");
  },
  updateLicense(payload: Record<string, unknown>) {
    return request<LicenseOverview["license"]>("/api/v1/license/me", {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },
  dashboard() {
    return request<DashboardSummary>("/api/v1/agent/dashboard/summary");
  },
  agents(params = "") {
    return request<{ items: Agent[]; total: number }>(`/api/v1/agent/list${params}`);
  },
  agent(agentId: string) {
    return request<Agent>(`/api/v1/agent/${encodeURIComponent(agentId)}`);
  },
  config(agentId: string) {
    return request<AgentConfig>(`/api/v1/config/${encodeURIComponent(agentId)}`);
  },
  agentConfigSchema() {
    return request<{ schema: AgentConfigSchema }>("/api/v1/config/schema");
  },
  updateConfig(agentId: string, config_json: Record<string, unknown>, config_version?: string) {
    return request<AgentConfig>(`/api/v1/config/${encodeURIComponent(agentId)}`, {
      method: "PUT",
      body: JSON.stringify({ config_json, config_version })
    });
  },
  alerts(params = "") {
    return request<AlertItem[]>(`/api/v1/alerts${params}`);
  },
  resolveAlert(id: number) {
    return request<AlertItem>(`/api/v1/alerts/${id}/resolve`, { method: "POST" });
  },
  acknowledgeAlert(id: number) {
    return request<AlertItem>(`/api/v1/alerts/${id}/acknowledge`, { method: "POST" });
  },
  logs(params = "") {
    return request<LogItem[]>(`/api/v1/logs${params}`);
  },
  // 通知渠道
  notificationChannels() {
    return request<NotificationChannel[]>("/api/v1/notifications/");
  },
  createNotificationChannel(payload: { name: string; channel_type: string; config: Record<string, unknown>; enabled?: boolean }) {
    return request<NotificationChannel>("/api/v1/notifications/", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  updateNotificationChannel(id: number, payload: { name?: string; config?: Record<string, unknown>; enabled?: boolean }) {
    return request<NotificationChannel>(`/api/v1/notifications/${id}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },
  deleteNotificationChannel(id: number) {
    return request<unknown>(`/api/v1/notifications/${id}`, { method: "DELETE" });
  },
  testNotificationChannel(id: number, message?: string) {
    return request<{ success: boolean; message: string }>(`/api/v1/notifications/${id}/test`, {
      method: "POST",
      body: JSON.stringify({ message: message || "测试通知" })
    });
  },
  forwardingLogs(params = "") {
    return request<ForwardingLog[]>(`/api/v1/notifications/forwarding-logs${params}`);
  },
  // 审计日志
  auditLogs(params = "") {
    return request<AuditLogItem[]>(`/api/v1/audit/${params}`);
  },
  auditStats() {
    return request<AuditStats>("/api/v1/audit/stats");
  },
  // 日志搜索
  logSearch(keyword: string, params = "") {
    return request<LogSearchResult>(`/api/v1/logs/search?keyword=${encodeURIComponent(keyword)}${params}`);
  },
  logStats(hours = 24) {
    return request<LogStats>(`/api/v1/logs/stats?hours=${hours}`);
  },
  // 平台配置
  platformConfig() {
    return request<PlatformConfig>("/api/v1/system-config/");
  },
  savePlatformConfig(config: Record<string, any>) {
    return request<PlatformConfigSaveResponse>("/api/v1/system-config/", {
      method: "PUT",
      body: JSON.stringify({ config })
    });
  },
  // 压力测试
  stressTests(params = "") {
    return request<{ items: StressTest[]; total: number }>(`/api/v1/stress-tests${params}`);
  },
  stressTest(testId: number) {
    return request<StressTest>(`/api/v1/stress-tests/${testId}`);
  },
  createStressTest(payload: {
    name: string; test_type: string; config: Record<string, any>; target_agent_ids: string[];
    is_recurring?: boolean; schedule_interval_seconds?: number | null;
  }) {
    return request<StressTest>("/api/v1/stress-tests", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  startStressTest(testId: number) {
    return request<StressTest>(`/api/v1/stress-tests/${testId}/start`, { method: "POST" });
  },
  stressTestReport(testId: number) {
    return request<any>(`/api/v1/stress-tests/${testId}/report`);
  },
  cancelStressTest(testId: number) {
    return request<StressTest>(`/api/v1/stress-tests/${testId}/cancel`, { method: "POST" });
  },
  deleteStressTest(testId: number) {
    return request<unknown>(`/api/v1/stress-tests/${testId}`, { method: "DELETE" });
  },
  // Agent 分组
  agentGroups() {
    return request<{ items: AgentGroup[]; total: number }>("/api/v1/agent-groups");
  },
  agentGroup(groupId: number) {
    return request<AgentGroup>(`/api/v1/agent-groups/${groupId}`);
  },
  createAgentGroup(payload: { name: string; description?: string; color?: string }) {
    return request<AgentGroup>("/api/v1/agent-groups", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  updateAgentGroup(groupId: number, payload: { name?: string; description?: string; color?: string }) {
    return request<AgentGroup>(`/api/v1/agent-groups/${groupId}`, {
      method: "PUT",
      body: JSON.stringify(payload)
    });
  },
  deleteAgentGroup(groupId: number) {
    return request<unknown>(`/api/v1/agent-groups/${groupId}`, { method: "DELETE" });
  },
  addGroupMembers(groupId: number, agentIds: string[]) {
    return request<AgentGroup>(`/api/v1/agent-groups/${groupId}/members`, {
      method: "POST",
      body: JSON.stringify(agentIds)
    });
  },
  removeGroupMember(groupId: number, agentId: string) {
    return request<unknown>(`/api/v1/agent-groups/${groupId}/members/${encodeURIComponent(agentId)}`, {
      method: "DELETE"
    });
  },
  // 远程命令
  remoteCommands(params = "") {
    return request<{ items: RemoteCommand[]; total: number }>(`/api/v1/remote-commands${params}`);
  },
  remoteCommand(commandId: number) {
    return request<RemoteCommand>(`/api/v1/remote-commands/${commandId}`);
  },
  createRemoteCommand(payload: {
    name: string; command_type: string; command_text: string; timeout_seconds?: number; target_agent_ids: string[];
  }) {
    return request<RemoteCommand>("/api/v1/remote-commands", {
      method: "POST",
      body: JSON.stringify(payload)
    });
  },
  startRemoteCommand(commandId: number) {
    return request<RemoteCommand>(`/api/v1/remote-commands/${commandId}/start`, { method: "POST" });
  },
  deleteRemoteCommand(commandId: number) {
    return request<unknown>(`/api/v1/remote-commands/${commandId}`, { method: "DELETE" });
  },
  // 文件分发
  fileDistributions(params = "") {
    return request<{ items: FileDistribution[]; total: number }>(`/api/v1/file-distributions${params}`);
  },
  fileDistribution(distId: number) {
    return request<FileDistribution>(`/api/v1/file-distributions/${distId}`);
  },
  createFileDistribution(formData: FormData) {
    const headers = new Headers();
    const token = localStorage.getItem("ops-platform-token") || "";
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return request<FileDistribution>("/api/v1/file-distributions", {
      method: "POST",
      body: formData,
      headers,
    });
  },
  startFileDistribution(distId: number) {
    return request<FileDistribution>(`/api/v1/file-distributions/${distId}/start`, { method: "POST" });
  },
  deleteFileDistribution(distId: number) {
    return request<unknown>(`/api/v1/file-distributions/${distId}`, { method: "DELETE" });
  },
  // 软件部署
  deployments(params = "") {
    return request<{ items: SoftwareDeployment[]; total: number }>(`/api/v1/deployments${params}`);
  },
  deployment(deploymentId: number) {
    return request<SoftwareDeployment>(`/api/v1/deployments/${deploymentId}`);
  },
  createDeployment(formData: FormData) {
    const headers = new Headers();
    const token = localStorage.getItem("ops-platform-token") || "";
    if (token) headers.set("Authorization", `Bearer ${token}`);
    return request<SoftwareDeployment>("/api/v1/deployments", {
      method: "POST",
      body: formData,
      headers,
    });
  },
  startDeployment(deploymentId: number) {
    return request<SoftwareDeployment>(`/api/v1/deployments/${deploymentId}/start`, { method: "POST" });
  },
  deleteDeployment(deploymentId: number) {
    return request<unknown>(`/api/v1/deployments/${deploymentId}`, { method: "DELETE" });
  }
};

export function connectAgentSocket(
  agentId: string,
  onMessage: (payload: unknown) => void,
  options?: { autoReconnect?: boolean; maxRetries?: number },
): WebSocket {
  const { autoReconnect = true, maxRetries = 10 } = options ?? {};
  let retries = 0;
  let closed = false;
  let latestSocket: WebSocket | null = null;

  function connect(): WebSocket {
    const token = getToken();
    const url = `${getWsBase()}/ws/agent/${encodeURIComponent(agentId)}${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    const socket = new WebSocket(url);
    latestSocket = socket;

    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        onMessage(event.data);
      }
    };

    socket.onclose = (event) => {
      if (closed || !autoReconnect) return;
      if (event.code === 4001 || event.code === 4003) return; // auth failures — don't retry
      if (retries < maxRetries) {
        retries++;
        const delay = Math.min(1000 * 2 ** retries, 30000);
        setTimeout(() => { if (!closed) connect(); }, delay);
      }
    };

    socket.onopen = () => { retries = 0; };
    return socket;
  }

  const socket = connect();
  // _opsClose 关闭最新活跃的 socket 并停止重连
  (socket as any)._opsClose = () => {
    closed = true;
    if (latestSocket && latestSocket.readyState <= WebSocket.OPEN) {
      latestSocket.close();
    }
  };
  return socket;
}

/**
 * 连接全局 Dashboard WebSocket — 接收告警和任务完成事件
 * 返回带 _opsClose() 方法的 WebSocket 实例
 */
export function connectDashboardSocket(
  onMessage: (payload: unknown) => void,
): WebSocket {
  let retries = 0;
  let closed = false;
  let latestSocket: WebSocket | null = null;

  function connect(): WebSocket {
    const token = getToken();
    const url = `${getWsBase()}/ws/dashboard${token ? `?token=${encodeURIComponent(token)}` : ""}`;
    const socket = new WebSocket(url);
    latestSocket = socket;

    socket.onmessage = (event) => {
      try {
        onMessage(JSON.parse(event.data));
      } catch {
        onMessage(event.data);
      }
    };

    socket.onclose = (event) => {
      if (closed) return;
      if (event.code === 4001 || event.code === 4003) return;
      if (retries < 30) {
        retries++;
        const delay = Math.min(1000 * 2 ** retries, 30000);
        setTimeout(() => { if (!closed) connect(); }, delay);
      }
    };

    socket.onopen = () => { retries = 0; };
    return socket;
  }

  const socket = connect();
  (socket as any)._opsClose = () => {
    closed = true;
    if (latestSocket && latestSocket.readyState <= WebSocket.OPEN) {
      latestSocket.close();
    }
  };
  return socket;
}
