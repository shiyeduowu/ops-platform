<script setup lang="ts">
import { ArrowLeft, Bell, Braces, FileText, RefreshCw, Save, Wifi, CheckCircle, Eye } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { api, connectAgentSocket } from "../api";
import EmptyState from "../components/EmptyState.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent, AgentConfig, AlertItem, LogItem, WsEvent } from "../types";

const route = useRoute();
const agentId = computed(() => String(route.params.agentId));
const agent = ref<Agent | null>(null);
const config = ref<AgentConfig | null>(null);
const logs = ref<LogItem[]>([]);
const alerts = ref<AlertItem[]>([]);
const liveMetrics = ref<Record<string, unknown>>({});
const configText = ref("");
const activeTab = ref<"overview" | "config" | "logs" | "alerts">("overview");
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const saveMessage = ref("");
const socketState = ref("connecting");
let socket: WebSocket | null = null;

const socketLabels: Record<string, string> = {
  connecting: "连接中",
  connected: "已连接",
  closed: "已断开",
  error: "连接异常"
};
const cpu = computed(() => Number(liveMetrics.value.cpu ?? agent.value?.last_metrics?.cpu ?? 0));
const mem = computed(() => Number(liveMetrics.value.mem ?? agent.value?.last_metrics?.mem ?? 0));
const ports = computed(() => (liveMetrics.value.ports || agent.value?.last_metrics?.ports || {}) as Record<string, unknown>);
const disks = computed(() => (liveMetrics.value.disk || agent.value?.last_metrics?.disk || []) as unknown[]);

function onSocketMessage(payload: unknown) {
  const event = payload as WsEvent;
  if (event.event === "metrics" && event.metrics) liveMetrics.value = event.metrics;
  if (event.event === "log" && event.log) logs.value = [event.log, ...logs.value].slice(0, 100);
  if (event.event === "alert" && event.alert) alerts.value = [event.alert, ...alerts.value].slice(0, 100);
  if (event.event === "config") saveMessage.value = `配置 ${event.config_version || ""} 已推送`;
}

function openSocket() {
  socket?.close();
  socketState.value = "connecting";
  socket = connectAgentSocket(agentId.value, onSocketMessage);
  // 不覆盖 connectAgentSocket 内部设置的 onopen（用于重置重试计数）
  // 使用 addEventListener 监听状态变化
  socket.addEventListener("open", () => { socketState.value = "connected"; });
  socket.addEventListener("close", () => { socketState.value = "closed"; });
  socket.addEventListener("error", () => { socketState.value = "error"; });
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [agentData, configData, logData, alertData] = await Promise.all([
      api.agent(agentId.value),
      api.config(agentId.value),
      api.logs(`?agent_id=${encodeURIComponent(agentId.value)}&limit=100`),
      api.alerts(`?agent_id=${encodeURIComponent(agentId.value)}&limit=100`)
    ]);
    agent.value = agentData;
    config.value = configData;
    liveMetrics.value = (agentData.last_metrics || {}) as Record<string, unknown>;
    configText.value = JSON.stringify(configData.config_json, null, 2);
    logs.value = logData;
    alerts.value = alertData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  saving.value = true;
  saveMessage.value = "";
  error.value = "";
  try {
    const parsed = JSON.parse(configText.value) as Record<string, unknown>;
    config.value = await api.updateConfig(agentId.value, parsed);
    configText.value = JSON.stringify(config.value.config_json, null, 2);
    saveMessage.value = `已保存 ${config.value.config_version}`;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function resolveAlert(id: number) {
  try {
    await api.resolveAlert(id);
    alerts.value = alerts.value.map((a) => a.id === id ? { ...a, status: "resolved" } : a);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  }
}

async function acknowledgeAlert(id: number) {
  try {
    await api.acknowledgeAlert(id);
    alerts.value = alerts.value.map((a) => a.id === id ? { ...a, status: "acknowledged" } : a);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  }
}

onMounted(() => {
  load();
  openSocket();
});

onBeforeUnmount(() => {
  socket?.close();
});
</script>

<template>
  <section class="content-stack">
    <div style="margin-bottom: 16px;">
      <button class="icon-button" @click="$router.back()">
        <ArrowLeft :size="16" />
        <span>返回</span>
      </button>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <section class="detail-hero">
      <div>
        <p class="eyebrow">{{ agent?.agent_id || agentId }}</p>
        <h2>{{ agent?.hostname || "Machine" }}</h2>
        <div class="hero-meta">
          <StatusBadge :value="agent?.status || 'unknown'" />
          <span>{{ agent?.ip || "-" }}</span>
          <span>{{ agent?.version || "-" }}</span>
        </div>
      </div>
      <div class="hero-actions">
        <span class="socket-state" :class="socketState">
          <Wifi :size="16" />
          {{ socketLabels[socketState] || socketState }}
        </span>
        <button class="icon-button" type="button" title="刷新详情" @click="load">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
      </div>
    </section>

    <div class="tab-bar">
      <button :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">概览</button>
      <button :class="{ active: activeTab === 'config' }" @click="activeTab = 'config'"><Braces :size="15" />配置</button>
      <button :class="{ active: activeTab === 'logs' }" @click="activeTab = 'logs'"><FileText :size="15" />日志</button>
      <button :class="{ active: activeTab === 'alerts' }" @click="activeTab = 'alerts'"><Bell :size="15" />告警</button>
    </div>

    <section v-if="activeTab === 'overview'" class="content-stack">
      <div class="stat-grid compact">
        <article class="stat-card tone-blue">
          <span>CPU</span>
          <strong>{{ cpu.toFixed(1) }}%</strong>
        </article>
        <article class="stat-card tone-green">
          <span>内存</span>
          <strong>{{ mem.toFixed(1) }}%</strong>
        </article>
        <article class="stat-card tone-amber">
          <span>端口</span>
          <strong>{{ Object.keys(ports).length }}</strong>
        </article>
        <article class="stat-card tone-slate">
          <span>磁盘</span>
          <strong>{{ disks.length }}</strong>
        </article>
      </div>

      <!-- 磁盘详情 -->
      <section v-if="disks.length" class="panel">
        <div class="panel-heading"><h2>磁盘使用</h2></div>
        <div class="disk-list">
          <div v-for="(disk, idx) in disks" :key="idx" class="disk-row">
            <span class="disk-mount">{{ (disk as any).mount || (disk as any).device || `磁盘 ${idx + 1}` }}</span>
            <div class="disk-bar-bg">
              <div
                class="disk-bar"
                :class="{ warning: (disk as any).percent > 80, critical: (disk as any).percent > 95 }"
                :style="{ width: `${(disk as any).percent || 0}%` }"
              ></div>
            </div>
            <span class="disk-percent">{{ ((disk as any).percent || 0).toFixed(1) }}%</span>
          </div>
        </div>
      </section>

      <!-- 端口状态 -->
      <section v-if="Object.keys(ports).length" class="panel">
        <div class="panel-heading"><h2>端口状态</h2></div>
        <div class="port-grid">
          <div v-for="(status, port) in ports" :key="port" class="port-chip" :class="status === 'open' ? 'port-open' : 'port-closed'">
            <span class="port-num">{{ port }}</span>
            <span class="port-status">{{ status === 'open' ? '正常' : '异常' }}</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading"><h2>原始指标</h2></div>
        <pre class="json-view">{{ JSON.stringify(liveMetrics, null, 2) }}</pre>
      </section>
    </section>

    <section v-if="activeTab === 'config'" class="panel">
      <div class="panel-heading">
        <h2>设备影子配置</h2>
        <span>{{ config?.config_version || "-" }}</span>
      </div>
      <textarea v-model="configText" class="code-editor" spellcheck="false"></textarea>
      <div class="form-actions">
        <span class="success-text">{{ saveMessage }}</span>
        <button class="primary-button fit" type="button" :disabled="saving" @click="saveConfig">
          <Save :size="17" />
          <span>{{ saving ? "保存中" : "保存" }}</span>
        </button>
      </div>
    </section>

    <section v-if="activeTab === 'logs'" class="panel">
      <div class="panel-heading"><h2>日志</h2><span>{{ logs.length }} 行</span></div>
      <EmptyState v-if="!logs.length && !loading" title="暂无日志" />
      <div v-else class="log-list">
        <article v-for="log in logs" :key="log.id" class="log-line">
          <time>{{ new Date(log.created_at).toLocaleTimeString() }}</time>
          <code>{{ log.service_key }}</code>
          <span>{{ log.content }}</span>
        </article>
      </div>
    </section>

    <section v-if="activeTab === 'alerts'" class="panel">
      <div class="panel-heading"><h2>告警</h2><span>{{ alerts.length }} 条记录</span></div>
      <EmptyState v-if="!alerts.length && !loading" title="暂无告警" />
      <div v-else class="event-list">
        <article v-for="alert in alerts" :key="alert.id" class="event-item">
          <div>
            <strong>{{ alert.type }}</strong>
            <span>{{ alert.message }}</span>
            <small class="alert-meta">{{ new Date(alert.created_at).toLocaleString() }} · {{ alert.status }}</small>
          </div>
          <div class="alert-actions">
            <StatusBadge :value="alert.severity" />
            <template v-if="alert.status === 'open'">
              <button class="icon-button sm" title="确认" @click="acknowledgeAlert(alert.id)">
                <Eye :size="14" />
              </button>
              <button class="icon-button sm success" title="解决" @click="resolveAlert(alert.id)">
                <CheckCircle :size="14" />
              </button>
            </template>
          </div>
        </article>
      </div>
    </section>
  </section>
</template>

<style scoped>
.alert-meta {
  display: block;
  font-size: 11px;
  color: var(--muted, #9ca3af);
  margin-top: 2px;
}
.alert-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}
.icon-button.sm {
  padding: 4px 6px;
  display: inline-flex;
}
.icon-button.success {
  color: #22c55e;
}
.icon-button.success:hover {
  background: #f0fdf4;
}

/* 磁盘 */
.disk-list {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.disk-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.disk-mount {
  width: 120px;
  font-size: 12px;
  font-family: monospace;
  color: var(--text, #374151);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.disk-bar-bg {
  flex: 1;
  height: 8px;
  background: #f3f4f6;
  border-radius: 4px;
  overflow: hidden;
}
.disk-bar {
  height: 100%;
  background: #3b82f6;
  border-radius: 4px;
  transition: width 0.5s ease;
}
.disk-bar.warning { background: #f59e0b; }
.disk-bar.critical { background: #ef4444; }
.disk-percent {
  width: 48px;
  text-align: right;
  font-size: 12px;
  font-weight: 600;
}

/* 端口 */
.port-grid {
  padding: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.port-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 500;
}
.port-open {
  background: #f0fdf4;
  color: #16a34a;
  border: 1px solid #bbf7d0;
}
.port-closed {
  background: #fef2f2;
  color: #ef4444;
  border: 1px solid #fecaca;
}
.port-num {
  font-family: monospace;
  font-weight: 600;
}
</style>
