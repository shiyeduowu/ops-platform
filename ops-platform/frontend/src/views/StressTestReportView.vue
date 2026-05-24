<script setup lang="ts">
import { ArrowLeft, Download } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api } from "../api";
import StatusBadge from "../components/StatusBadge.vue";

const route = useRoute();
const router = useRouter();
const report = ref<any>(null);
const loading = ref(false);
const error = ref("");

const testTypeLabels: Record<string, string> = {
  network_bandwidth: "网络带宽",
  network_latency: "网络延迟",
  network_packet_loss: "网络丢包",
  disk_io: "磁盘 I/O",
  cpu_stress: "CPU 压力",
  memory_stress: "内存压力",
  browser_automation: "浏览器自动化",
  http_api: "HTTP API 压测",
};

function formatDuration(seconds: number | null): string {
  if (seconds === null || seconds === undefined) return "-";
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}

function exportJson() {
  if (!report.value) return;
  const blob = new Blob([JSON.stringify(report.value, null, 2)], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `stress-test-report-${report.value.test_id}.json`;
  a.click();
  URL.revokeObjectURL(url);
}

onMounted(async () => {
  const testId = Number(route.params.testId);
  loading.value = true;
  try {
    report.value = await api.stressTestReport(testId);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
});
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <button class="btn" @click="router.back()"><ArrowLeft :size="16" /> 返回</button>
      <div style="flex:1"></div>
      <button v-if="report" class="btn" @click="exportJson"><Download :size="16" /> 导出 JSON</button>
    </div>

    <div v-if="loading" class="loading-row">加载中...</div>
    <p v-else-if="error" class="alert-line">{{ error }}</p>

    <template v-else-if="report">
      <!-- 概要卡片 -->
      <div class="report-header">
        <h2>{{ report.test_name }}</h2>
        <div class="report-meta">
          <span class="tag">{{ testTypeLabels[report.test_type] || report.test_type }}</span>
          <StatusBadge :value="report.status" />
          <span class="meta-item">创建者: {{ report.created_by }}</span>
          <span class="meta-item">目标数: {{ report.agents_count }}</span>
          <span class="meta-item">持续: {{ formatDuration(report.duration_seconds) }}</span>
        </div>
      </div>

      <!-- 汇总指标 -->
      <div v-if="report.test_type === 'http_api'" class="metrics-grid">
        <div class="metric-card">
          <span class="metric-label">总请求数</span>
          <span class="metric-value">{{ report.summary.total_requests }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">成功数</span>
          <span class="metric-value success">{{ report.summary.total_success }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">失败数</span>
          <span class="metric-value" :class="{ fail: report.summary.total_errors > 0 }">{{ report.summary.total_errors }}</span>
        </div>
        <div class="metric-card">
          <span class="metric-label">总成功率</span>
          <span class="metric-value" :class="{ success: report.summary.overall_success_rate >= 99, warn: report.summary.overall_success_rate < 99 }">
            {{ report.summary.overall_success_rate }}%
          </span>
        </div>
      </div>

      <!-- 各 Agent 结果 -->
      <h3 class="section-title">各 Agent 结果</h3>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Agent</th>
              <th>状态</th>
              <template v-if="report.test_type === 'http_api'">
                <th>请求数</th>
                <th>成功率</th>
                <th>QPS</th>
                <th>耗时</th>
              </template>
              <template v-else>
                <th>详情</th>
              </template>
            </tr>
          </thead>
          <tbody>
            <tr v-for="agent in report.per_agent" :key="agent.agent_id">
              <td>{{ agent.agent_id }}</td>
              <td><StatusBadge :value="agent.status" /></td>
              <template v-if="report.test_type === 'http_api'">
                <td>{{ agent.total_requests || 0 }}</td>
                <td>{{ agent.total_requests ? ((agent.total_success / agent.total_requests * 100).toFixed(1)) : 0 }}%</td>
                <td>{{ agent.overall_qps || 0 }}</td>
                <td>{{ formatDuration(agent.duration_seconds) }}</td>
              </template>
              <template v-else>
                <td class="detail-cell">
                  <span v-if="agent.error_message" class="error-text">{{ agent.error_message }}</span>
                  <span v-else-if="agent.summary">{{ agent.summary }}</span>
                  <span v-else-if="agent.metrics">{{ JSON.stringify(agent.metrics).slice(0, 100) }}...</span>
                  <span v-else>-</span>
                </td>
              </template>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 配置信息 -->
      <h3 class="section-title">测试配置</h3>
      <div class="config-block">
        <pre>{{ JSON.stringify(report.config, null, 2) }}</pre>
      </div>
    </template>
  </section>
</template>

<style scoped>
.tag {
  display: inline-block;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-alt, #1e293b);
  color: var(--muted, #94a3b8);
}
.report-header {
  margin-bottom: 24px;
}
.report-header h2 {
  font-size: 22px;
  margin-bottom: 10px;
}
.report-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.meta-item {
  font-size: 13px;
  color: var(--muted, #94a3b8);
}
.metrics-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 12px;
  margin-bottom: 24px;
}
.metric-card {
  background: var(--surface, #1e293b);
  border-radius: 10px;
  padding: 16px;
  border: 1px solid var(--line, #334155);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.metric-label {
  font-size: 12px;
  color: var(--muted, #94a3b8);
  text-transform: uppercase;
}
.metric-value {
  font-size: 28px;
  font-weight: 700;
}
.metric-value.success {
  color: #22c55e;
}
.metric-value.fail {
  color: #ef4444;
}
.metric-value.warn {
  color: #f59e0b;
}
.section-title {
  font-size: 16px;
  color: var(--muted, #94a3b8);
  margin: 24px 0 12px;
}
.detail-cell {
  max-width: 300px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}
.error-text {
  color: #f87171;
}
.config-block {
  background: var(--surface, #1e293b);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--line, #334155);
}
.config-block pre {
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
</style>
