<script setup lang="ts">
import { Download, Filter, RefreshCw, CheckCircle, Eye } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";
import { exportCsv } from "../export";
import EmptyState from "../components/EmptyState.vue";
import StatusBadge from "../components/StatusBadge.vue";
import { bus, toast } from "../events";
import type { AlertItem } from "../types";

const alerts = ref<AlertItem[]>([]);
const statusFilter = ref("");
const severityFilter = ref("");
const loading = ref(false);
const error = ref("");
const actionLoading = ref<number | null>(null);

const queryString = computed(() => {
  const params = new URLSearchParams();
  params.set("limit", "300");
  if (statusFilter.value) params.set("status", statusFilter.value);
  if (severityFilter.value) params.set("severity", severityFilter.value);
  return `?${params.toString()}`;
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    alerts.value = await api.alerts(queryString.value);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function resolveAlert(id: number) {
  actionLoading.value = id;
  try {
    await api.resolveAlert(id);
    toast("告警已解决");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  } finally {
    actionLoading.value = null;
  }
}

async function acknowledgeAlert(id: number) {
  actionLoading.value = id;
  try {
    await api.acknowledgeAlert(id);
    toast("告警已确认");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "操作失败";
  } finally {
    actionLoading.value = null;
  }
}

function onNewAlert(alert: AlertItem) {
  // 将新告警插入列表顶部（如果符合当前筛选条件）
  if (statusFilter.value && alert.status !== statusFilter.value) return;
  if (severityFilter.value && alert.severity !== severityFilter.value) return;
  alerts.value = [alert, ...alerts.value.filter((a) => a.id !== alert.id)];
}

function exportData() {
  exportCsv(
    "alerts.csv",
    ["type", "severity", "status", "agent_id", "message", "created_at"],
    alerts.value.map((a) => [a.type, a.severity, a.status, a.agent_id, a.message, new Date(a.created_at).toLocaleString()]),
  );
}

onMounted(() => {
  load();
  bus.on("alert", onNewAlert);
});
onUnmounted(() => bus.off("alert", onNewAlert));
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <label class="select-box">
        <Filter :size="17" />
        <select v-model="statusFilter" @change="load">
          <option value="">全部状态</option>
          <option value="open">未处理</option>
          <option value="acknowledged">已确认</option>
          <option value="resolved">已恢复</option>
        </select>
      </label>
      <label class="select-box">
        <select v-model="severityFilter" @change="load">
          <option value="">全部级别</option>
          <option value="critical">严重</option>
          <option value="warning">警告</option>
          <option value="info">提示</option>
        </select>
      </label>
      <button class="icon-button" type="button" title="刷新告警" @click="load">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
      <button class="icon-button" type="button" @click="exportData">
        <Download :size="17" />
        <span>导出</span>
      </button>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <section class="panel">
      <div class="panel-heading">
        <h2>告警列表</h2>
        <span>{{ alerts.length }} 条记录</span>
      </div>
      <div v-if="loading" class="loading-row">加载中</div>
      <EmptyState v-else-if="!alerts.length" title="暂无告警" />
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>类型</th>
              <th>级别</th>
              <th>状态</th>
              <th>Agent</th>
              <th>内容</th>
              <th>创建时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="alert in alerts" :key="alert.id">
              <td>{{ alert.type }}</td>
              <td><StatusBadge :value="alert.severity" /></td>
              <td><StatusBadge :value="alert.status" /></td>
              <td><code>{{ alert.agent_id }}</code></td>
              <td>{{ alert.message }}</td>
              <td>{{ new Date(alert.created_at).toLocaleString() }}</td>
              <td>
                <template v-if="alert.status === 'open'">
                  <button
                    class="icon-button sm"
                    title="确认"
                    :disabled="actionLoading === alert.id"
                    @click="acknowledgeAlert(alert.id)"
                  >
                    <Eye :size="14" />
                  </button>
                  <button
                    class="icon-button sm success"
                    title="解决"
                    :disabled="actionLoading === alert.id"
                    @click="resolveAlert(alert.id)"
                  >
                    <CheckCircle :size="14" />
                  </button>
                </template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<style scoped>
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
</style>
