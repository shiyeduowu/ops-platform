<script setup lang="ts">
import { AlertTriangle, Cpu, RadioTower, Server, ShieldCheck, Clock } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "../api";
import EmptyState from "../components/EmptyState.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { DashboardSummary, AlertItem } from "../types";

const loading = ref(true);
const error = ref("");
const summary = ref<DashboardSummary | null>(null);
const lastRefresh = ref("");

const cards = computed(() => {
  const data = summary.value;
  return [
    { label: "Agent 总数", value: data?.total_agents ?? 0, icon: Server, tone: "blue" },
    { label: "在线机器", value: data?.online_agents ?? 0, icon: RadioTower, tone: "green" },
    { label: "离线机器", value: data?.offline_agents ?? 0, icon: Cpu, tone: "slate" },
    { label: "未处理告警", value: data?.open_alerts ?? 0, icon: AlertTriangle, tone: "amber" }
  ];
});

const alertStats = computed(() => {
  const alerts = summary.value?.recent_alerts ?? [];
  const bySeverity = { critical: 0, warning: 0, info: 0 };
  const byType: Record<string, number> = {};
  for (const a of alerts) {
    bySeverity[a.severity as keyof typeof bySeverity] = (bySeverity[a.severity as keyof typeof bySeverity] || 0) + 1;
    byType[a.type] = (byType[a.type] || 0) + 1;
  }
  return { bySeverity, byType, total: alerts.length };
});

const topAlertTypes = computed(() => {
  return Object.entries(alertStats.value.byType)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    summary.value = await api.dashboard();
    lastRefresh.value = new Date().toLocaleTimeString();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

let timer: ReturnType<typeof setInterval> | null = null;

onMounted(() => {
  load();
  timer = setInterval(load, 30000);
});

onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <div class="toolbar-info">
        <Clock :size="14" />
        <span>上次刷新: {{ lastRefresh || "-" }}</span>
        <span class="auto-refresh-hint">每 30 秒自动刷新</span>
      </div>
    </div>
    <div v-if="error" class="alert-line">{{ error }}</div>

    <div class="stat-grid">
      <article v-for="card in cards" :key="card.label" class="stat-card" :class="`tone-${card.tone}`">
        <component :is="card.icon" :size="22" />
        <div>
          <span>{{ card.label }}</span>
          <strong>{{ card.value }}</strong>
        </div>
      </article>
    </div>

    <div class="two-column">
      <section class="panel">
        <div class="panel-heading">
          <h2>机器状态</h2>
          <RouterLink class="text-link" to="/agents">查看全部</RouterLink>
        </div>
        <div v-if="loading" class="loading-row">加载中</div>
        <EmptyState v-else-if="!summary?.agent_list.length" title="暂无已注册 Agent" />
        <div v-else class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>主机名</th>
                <th>状态</th>
                <th>版本</th>
                <th>最后心跳</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="agent in summary.agent_list.slice(0, 8)" :key="agent.agent_id">
                <td>
                  <RouterLink class="strong-link" :to="`/agents/${agent.agent_id}`">{{ agent.hostname }}</RouterLink>
                  <small>{{ agent.ip || agent.agent_id }}</small>
                </td>
                <td><StatusBadge :value="agent.status" /></td>
                <td>{{ agent.version }}</td>
                <td>{{ agent.last_seen ? new Date(agent.last_seen).toLocaleString() : "-" }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h2>最近告警</h2>
          <RouterLink class="text-link" to="/alerts">打开告警中心</RouterLink>
        </div>
        <EmptyState v-if="!summary?.recent_alerts.length && !loading" title="暂无告警" />
        <div v-else class="event-list">
          <article v-for="alert in summary?.recent_alerts.slice(0, 8)" :key="alert.id" class="event-item">
            <div>
              <strong>{{ alert.type }}</strong>
              <span>{{ alert.message }}</span>
            </div>
            <StatusBadge :value="alert.severity" />
          </article>
        </div>
      </section>
    </div>

    <!-- 告警统计 -->
    <div v-if="summary?.recent_alerts.length" class="two-column">
      <section class="panel">
        <div class="panel-heading">
          <h2><ShieldCheck :size="16" style="vertical-align:-2px;margin-right:6px" />告警级别分布</h2>
        </div>
        <div class="severity-bars">
          <div class="severity-row">
            <span class="severity-label critical">严重</span>
            <div class="severity-bar-bg">
              <div class="severity-bar critical" :style="{ width: alertStats.total ? `${(alertStats.bySeverity.critical / alertStats.total) * 100}%` : '0%' }"></div>
            </div>
            <span class="severity-count">{{ alertStats.bySeverity.critical }}</span>
          </div>
          <div class="severity-row">
            <span class="severity-label warning">警告</span>
            <div class="severity-bar-bg">
              <div class="severity-bar warning" :style="{ width: alertStats.total ? `${(alertStats.bySeverity.warning / alertStats.total) * 100}%` : '0%' }"></div>
            </div>
            <span class="severity-count">{{ alertStats.bySeverity.warning }}</span>
          </div>
          <div class="severity-row">
            <span class="severity-label info">提示</span>
            <div class="severity-bar-bg">
              <div class="severity-bar info" :style="{ width: alertStats.total ? `${(alertStats.bySeverity.info / alertStats.total) * 100}%` : '0%' }"></div>
            </div>
            <span class="severity-count">{{ alertStats.bySeverity.info }}</span>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h2>告警类型 TOP {{ topAlertTypes.length }}</h2>
        </div>
        <div class="alert-type-list">
          <div v-for="[type, count] in topAlertTypes" :key="type" class="alert-type-row">
            <span class="alert-type-name">{{ type }}</span>
            <div class="alert-type-bar-bg">
              <div class="alert-type-bar" :style="{ width: `${(count / (topAlertTypes[0]?.[1] || 1)) * 100}%` }"></div>
            </div>
            <span class="alert-type-count">{{ count }}</span>
          </div>
        </div>
      </section>
    </div>
  </section>
</template>

<style scoped>
.toolbar-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted, #6b7280);
}
.auto-refresh-hint {
  margin-left: 8px;
  padding: 2px 8px;
  background: #f0fdf4;
  color: #16a34a;
  border-radius: 4px;
  font-size: 11px;
}

/* 告警级别分布 */
.severity-bars {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.severity-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.severity-label {
  width: 36px;
  font-size: 12px;
  font-weight: 600;
}
.severity-label.critical { color: #ef4444; }
.severity-label.warning { color: #f59e0b; }
.severity-label.info { color: #3b82f6; }
.severity-bar-bg {
  flex: 1;
  height: 8px;
  background: #f3f4f6;
  border-radius: 4px;
  overflow: hidden;
}
.severity-bar {
  height: 100%;
  border-radius: 4px;
  transition: width 0.5s ease;
}
.severity-bar.critical { background: #ef4444; }
.severity-bar.warning { background: #f59e0b; }
.severity-bar.info { background: #3b82f6; }
.severity-count {
  width: 28px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
}

/* 告警类型 */
.alert-type-list {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.alert-type-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.alert-type-name {
  width: 120px;
  font-size: 12px;
  color: var(--text, #374151);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.alert-type-bar-bg {
  flex: 1;
  height: 8px;
  background: #f3f4f6;
  border-radius: 4px;
  overflow: hidden;
}
.alert-type-bar {
  height: 100%;
  background: linear-gradient(90deg, #667eea, #764ba2);
  border-radius: 4px;
  transition: width 0.5s ease;
}
.alert-type-count {
  width: 28px;
  text-align: right;
  font-size: 13px;
  font-weight: 600;
}
</style>
