<script setup lang="ts">
import {
  Filter,
  RefreshCw,
  ShieldCheck,
  User,
  Activity,
  Clock,
  BarChart3
} from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api } from "../api";
import EmptyState from "../components/EmptyState.vue";
import type { AuditLogItem, AuditStats } from "../types";

const logs = ref<AuditLogItem[]>([]);
const stats = ref<AuditStats | null>(null);
const loading = ref(false);
const error = ref("");
const actionFilter = ref("");
const resourceFilter = ref("");

const queryString = computed(() => {
  const params = new URLSearchParams();
  params.set("limit", "200");
  if (actionFilter.value) params.set("action", actionFilter.value);
  if (resourceFilter.value) params.set("resource_type", resourceFilter.value);
  return `?${params.toString()}`;
});

const actionLabels: Record<string, string> = {
  login: "登录",
  create: "创建",
  update: "更新",
  delete: "删除",
  export: "导出",
};

const resourceLabels: Record<string, string> = {
  agent: "机器",
  config: "配置",
  alert: "告警",
  channel: "通知渠道",
  user: "用户",
  license: "授权",
};

function actionColor(action: string) {
  const map: Record<string, string> = {
    login: "#3b82f6",
    create: "#22c55e",
    update: "#f59e0b",
    delete: "#ef4444",
    export: "#8b5cf6",
  };
  return map[action] || "#6b7280";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [logsRes, statsRes] = await Promise.all([
      api.auditLogs(queryString.value),
      api.auditStats(),
    ]);
    logs.value = logsRes;
    stats.value = statsRes;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <!-- 统计卡片 -->
    <div v-if="stats" class="stat-row">
      <div class="stat-card">
        <div class="stat-icon" style="background:#3b82f618;color:#3b82f6"><ShieldCheck :size="20" /></div>
        <div>
          <p class="stat-label">总记录</p>
          <p class="stat-value">{{ stats.total }}</p>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:#22c55e18;color:#22c55e"><Clock :size="20" /></div>
        <div>
          <p class="stat-label">今日操作</p>
          <p class="stat-value">{{ stats.today }}</p>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:#f59e0b18;color:#f59e0b"><Activity :size="20" /></div>
        <div>
          <p class="stat-label">操作类型</p>
          <p class="stat-value">{{ Object.keys(stats.by_action).length }}</p>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:#8b5cf618;color:#8b5cf6"><BarChart3 :size="20" /></div>
        <div>
          <p class="stat-label">资源类型</p>
          <p class="stat-value">{{ Object.keys(stats.by_resource).length }}</p>
        </div>
      </div>
    </div>

    <div class="toolbar">
      <label class="select-box">
        <Filter :size="17" />
        <select v-model="actionFilter" @change="load">
          <option value="">全部操作</option>
          <option v-for="(label, key) in actionLabels" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <label class="select-box">
        <Filter :size="17" />
        <select v-model="resourceFilter" @change="load">
          <option value="">全部资源</option>
          <option v-for="(label, key) in resourceLabels" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <button class="icon-button" type="button" @click="load">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <section class="panel">
      <div class="panel-heading">
        <h2>审计日志</h2>
        <span>{{ logs.length }} 条记录</span>
      </div>
      <div v-if="loading" class="loading-row">加载中</div>
      <EmptyState v-else-if="!logs.length" title="暂无审计记录" />
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>用户</th>
              <th>操作</th>
              <th>资源类型</th>
              <th>资源ID</th>
              <th>IP地址</th>
              <th>详情</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id">
              <td class="time-cell">{{ new Date(log.created_at).toLocaleString() }}</td>
              <td>
                <span class="user-badge">
                  <User :size="13" />
                  {{ log.username }}
                </span>
              </td>
              <td>
                <span class="action-tag" :style="{ background: actionColor(log.action) + '18', color: actionColor(log.action) }">
                  {{ actionLabels[log.action] || log.action }}
                </span>
              </td>
              <td>{{ resourceLabels[log.resource_type] || log.resource_type }}</td>
              <td><code v-if="log.resource_id">{{ log.resource_id }}</code><span v-else>-</span></td>
              <td><code v-if="log.ip_address">{{ log.ip_address }}</code><span v-else>-</span></td>
              <td class="detail-cell">
                <span v-if="log.details" :title="JSON.stringify(log.details)">{{ Object.keys(log.details).length }} 项</span>
                <span v-else>-</span>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 12px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 10px;
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e5e7eb);
}
.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-label {
  font-size: 12px;
  opacity: 0.6;
  margin: 0;
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
}
.time-cell {
  font-size: 12px;
  white-space: nowrap;
}
.user-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
}
.action-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 600;
}
.detail-cell {
  font-size: 12px;
  opacity: 0.7;
}
</style>
