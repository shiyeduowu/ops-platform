<script setup lang="ts">
import { ArrowLeft, Play, XCircle, RefreshCw, Zap, Activity } from "lucide-vue-next";
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { api, connectAgentSocket } from "../api";
import StatusBadge from "../components/StatusBadge.vue";
import type { StressTest, StressTestResult } from "../types";

const route = useRoute();
const router = useRouter();
const testId = Number(route.params.testId);

const test = ref<StressTest | null>(null);
const loading = ref(false);
const error = ref("");
const actionLoading = ref(false);
const activeTab = ref<"overview" | "targets" | "results" | "config" | "monitor">("overview");

const sockets: WebSocket[] = [];

// 监控数据
interface MonitorPoint {
  agent_id: string;
  cpu_percent: number;
  memory_percent: number;
  memory_used_mb: number;
  net_sent_kbps: number;
  net_recv_kbps: number;
  timestamp: number;
}
const monitorData = ref<Map<string, MonitorPoint[]>>(new Map());
const MAX_POINTS = 120;
const cpuCanvas = ref<HTMLCanvasElement | null>(null);
const memCanvas = ref<HTMLCanvasElement | null>(null);
const netCanvas = ref<HTMLCanvasElement | null>(null);
const monitorGridRef = ref<HTMLDivElement | null>(null);
let resizeObserver: ResizeObserver | null = null;

const testTypeLabels: Record<string, string> = {
  network_bandwidth: "网络带宽",
  network_latency: "网络延迟",
  network_packet_loss: "网络丢包",
  disk_io: "磁盘 I/O",
  cpu_stress: "CPU 压力",
  memory_stress: "内存压力",
  browser_automation: "浏览器自动化",
};

const statusLabels: Record<string, string> = {
  draft: "草稿",
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const targetStats = computed(() => {
  if (!test.value) return { total: 0, completed: 0, running: 0, failed: 0 };
  const targets = test.value.targets;
  return {
    total: targets.length,
    completed: targets.filter(t => t.status === "completed").length,
    running: targets.filter(t => t.status === "running").length,
    failed: targets.filter(t => t.status === "failed").length,
    pending: targets.filter(t => t.status === "pending").length,
  };
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    test.value = await api.stressTest(testId);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function startTest() {
  actionLoading.value = true;
  try {
    test.value = await api.startStressTest(testId);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "启动失败";
  } finally {
    actionLoading.value = false;
  }
}

async function cancelTest() {
  actionLoading.value = true;
  try {
    test.value = await api.cancelStressTest(testId);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "取消失败";
  } finally {
    actionLoading.value = false;
  }
}

function getResultForAgent(agentId: string): StressTestResult | undefined {
  return test.value?.results.find(r => r.agent_id === agentId);
}

function formatResultData(data: Record<string, any> | null): string {
  if (!data) return "无数据";
  return JSON.stringify(data, null, 2);
}

function setupWebSocket() {
  if (!test.value) return;
  const agentIds = new Set(test.value.targets.map(t => t.agent_id));
  for (const agentId of agentIds) {
    const ws = connectAgentSocket(agentId, (payload: any) => {
      if (payload?.event === "stress_test_result" && payload.test_id === testId) {
        load();
      }
      if (payload?.event === "stress_test_monitor" && payload.test_id === testId) {
        const metrics = payload.metrics;
        const aid = payload.agent_id;
        if (!metrics) return;
        const points = monitorData.value.get(aid) || [];
        points.push({
          agent_id: aid,
          cpu_percent: metrics.cpu_percent || 0,
          memory_percent: metrics.memory_percent || 0,
          memory_used_mb: metrics.memory_used_mb || 0,
          net_sent_kbps: metrics.net_sent_kbps || 0,
          net_recv_kbps: metrics.net_recv_kbps || 0,
          timestamp: metrics.timestamp || Date.now() / 1000,
        });
        if (points.length > MAX_POINTS) points.shift();
        monitorData.value.set(aid, [...points]);
        drawCharts();
      }
    });
    sockets.push(ws);
  }
}

function syncCanvasSize(canvas: HTMLCanvasElement) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.round(rect.width * dpr);
  const h = Math.round(rect.height * dpr);
  if (canvas.width !== w || canvas.height !== h) {
    canvas.width = w;
    canvas.height = h;
    return true;
  }
  return false;
}

function drawCharts() {
  [cpuCanvas.value, memCanvas.value, netCanvas.value].forEach(c => {
    if (c) syncCanvasSize(c);
  });
  drawLineChart(cpuCanvas.value, "CPU %", monitorData.value, "cpu_percent", "#60a5fa", 100);
  drawLineChart(memCanvas.value, "内存 %", monitorData.value, "memory_percent", "#34d399", 100);
  drawLineChart(netCanvas.value, "网络 KB/s", monitorData.value, "net_recv_kbps", "#f59e0b");
}

function setupResizeObserver() {
  if (resizeObserver) resizeObserver.disconnect();
  resizeObserver = new ResizeObserver(() => {
    drawCharts();
  });
  nextTick(() => {
    if (monitorGridRef.value) resizeObserver!.observe(monitorGridRef.value);
  });
}

function drawLineChart(
  canvas: HTMLCanvasElement | null,
  label: string,
  dataMap: Map<string, MonitorPoint[]>,
  key: keyof MonitorPoint,
  color: string,
  maxVal?: number,
) {
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const W = canvas.width / dpr;
  const H = canvas.height / dpr;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, W, H);

  // 背景
  ctx.fillStyle = "#0f172a";
  ctx.fillRect(0, 0, W, H);

  // 标题
  ctx.fillStyle = "#94a3b8";
  ctx.font = "12px sans-serif";
  ctx.fillText(label, 8, 16);

  const allPoints: MonitorPoint[] = [];
  for (const pts of dataMap.values()) allPoints.push(...pts);
  if (allPoints.length < 2) {
    ctx.fillStyle = "#475569";
    ctx.fillText("等待数据...", W / 2 - 30, H / 2);
    return;
  }

  const values = allPoints.map(p => p[key] as number);
  const max = maxVal ?? Math.max(...values, 1) * 1.1;
  const padding = { top: 28, bottom: 20, left: 8, right: 8 };
  const chartW = W - padding.left - padding.right;
  const chartH = H - padding.top - padding.bottom;

  // 网格线
  ctx.strokeStyle = "#1e293b";
  ctx.lineWidth = 1;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(W - padding.right, y);
    ctx.stroke();
  }

  // 绘制每个 Agent 的线
  const colors = ["#60a5fa", "#34d399", "#f472b6", "#a78bfa", "#fbbf24"];
  let ci = 0;
  for (const [agentId, points] of dataMap.entries()) {
    if (points.length < 2) continue;
    const lineColor = colors[ci % colors.length];
    ci++;
    const sorted = [...points].sort((a, b) => a.timestamp - b.timestamp);
    ctx.strokeStyle = lineColor;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    for (let i = 0; i < sorted.length; i++) {
      const x = padding.left + (i / (sorted.length - 1)) * chartW;
      const val = sorted[i][key] as number;
      const y = padding.top + chartH - (val / max) * chartH;
      if (i === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();
  }

  // Y轴标签
  ctx.fillStyle = "#64748b";
  ctx.font = "10px sans-serif";
  ctx.fillText(`${Math.round(max)}`, 2, padding.top + 10);
  ctx.fillText("0", 2, H - padding.bottom);
}

watch(activeTab, (tab) => {
  if (tab === "monitor") {
    nextTick(() => {
      drawCharts();
      setupResizeObserver();
    });
  }
});

onMounted(async () => {
  await load();
  setupWebSocket();
});

onUnmounted(() => {
  for (const ws of sockets) {
    try { (ws as any)._opsClose ? (ws as any)._opsClose() : ws.close(); } catch {}
  }
  if (resizeObserver) {
    resizeObserver.disconnect();
    resizeObserver = null;
  }
});
</script>

<template>
  <section class="content-stack">
    <!-- 头部 -->
    <div class="detail-header">
      <button class="btn sm" @click="router.push('/stress-tests')">
        <ArrowLeft :size="16" /> 返回
      </button>
      <div v-if="test" class="header-info">
        <h2>{{ test.name }}</h2>
        <StatusBadge :value="test.status" />
        <span class="tag">{{ testTypeLabels[test.test_type] || test.test_type }}</span>
      </div>
      <div v-if="test" class="header-actions">
        <button v-if="test.status === 'draft' || test.status === 'failed'" class="btn primary" :disabled="actionLoading" @click="startTest">
          <Play :size="16" /> 启动测试
        </button>
        <button v-if="test.status === 'pending' || test.status === 'running'" class="btn warn" :disabled="actionLoading" @click="cancelTest">
          <XCircle :size="16" /> 取消
        </button>
        <button class="btn" @click="load"><RefreshCw :size="16" /> 刷新</button>
      </div>
    </div>

    <p v-if="error" class="alert-line">{{ error }}</p>
    <div v-if="loading" class="loading-row">加载中...</div>

    <template v-if="test && !loading">
      <!-- Tab 栏 -->
      <div class="tab-bar">
        <button :class="{ active: activeTab === 'overview' }" @click="activeTab = 'overview'">概览</button>
        <button :class="{ active: activeTab === 'targets' }" @click="activeTab = 'targets'">目标 ({{ test.targets.length }})</button>
        <button :class="{ active: activeTab === 'results' }" @click="activeTab = 'results'">结果 ({{ test.results.length }})</button>
        <button :class="{ active: activeTab === 'monitor' }" @click="activeTab = 'monitor'">
          <Activity :size="14" style="vertical-align:middle;margin-right:4px" /> 监控
        </button>
        <button :class="{ active: activeTab === 'config' }" @click="activeTab = 'config'">配置</button>
      </div>

      <!-- 概览 Tab -->
      <div v-if="activeTab === 'overview'" class="overview-grid">
        <div class="stat-card">
          <div class="stat-label">目标总数</div>
          <div class="stat-value">{{ targetStats.total }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">已完成</div>
          <div class="stat-value" style="color: #22c55e">{{ targetStats.completed }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">运行中</div>
          <div class="stat-value" style="color: #60a5fa">{{ targetStats.running }}</div>
        </div>
        <div class="stat-card">
          <div class="stat-label">失败</div>
          <div class="stat-value" style="color: #ef4444">{{ targetStats.failed }}</div>
        </div>

        <div class="info-panel">
          <h4>基本信息</h4>
          <div class="info-row"><span>创建者</span><span>{{ test.created_by }}</span></div>
          <div class="info-row"><span>创建时间</span><span>{{ new Date(test.created_at).toLocaleString() }}</span></div>
          <div class="info-row"><span>启动时间</span><span>{{ test.started_at ? new Date(test.started_at).toLocaleString() : '-' }}</span></div>
          <div class="info-row"><span>结束时间</span><span>{{ test.finished_at ? new Date(test.finished_at).toLocaleString() : '-' }}</span></div>
        </div>
      </div>

      <!-- 目标 Tab -->
      <div v-if="activeTab === 'targets'" class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Agent ID</th>
              <th>状态</th>
              <th>命令已接收</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="t in test.targets" :key="t.id">
              <td><code>{{ t.agent_id }}</code></td>
              <td><StatusBadge :value="t.status" /></td>
              <td>{{ t.command_acked ? '是' : '否' }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 结果 Tab -->
      <div v-if="activeTab === 'results'">
        <div v-if="test.results.length === 0" class="empty-hint">
          暂无结果，启动测试后将在此显示
        </div>
        <div v-else class="results-list">
          <div v-for="r in test.results" :key="r.id" class="result-card">
            <div class="result-header">
              <code>{{ r.agent_id }}</code>
              <StatusBadge :value="r.status" />
              <span v-if="r.started_at" class="time">{{ new Date(r.started_at).toLocaleString() }}</span>
            </div>
            <div v-if="r.error_message" class="result-error">{{ r.error_message }}</div>
            <pre v-if="r.result_data" class="result-data">{{ formatResultData(r.result_data) }}</pre>
          </div>
        </div>
      </div>

      <!-- 监控 Tab -->
      <div v-if="activeTab === 'monitor'">
        <div v-if="monitorData.size === 0" class="empty-hint">
          暂无实时数据，测试启动后将在此显示 CPU/内存/网络曲线
        </div>
        <div v-else ref="monitorGridRef" class="monitor-grid">
          <div class="chart-card">
            <canvas ref="cpuCanvas"></canvas>
          </div>
          <div class="chart-card">
            <canvas ref="memCanvas"></canvas>
          </div>
          <div class="chart-card">
            <canvas ref="netCanvas"></canvas>
          </div>
        </div>
        <div v-if="monitorData.size > 0" class="monitor-legend">
          <span v-for="[agentId] in monitorData" :key="agentId" class="legend-item">
            <span class="legend-dot"></span> {{ agentId.slice(0, 12) }}...
          </span>
        </div>
      </div>

      <!-- 配置 Tab -->
      <div v-if="activeTab === 'config'">
        <pre class="json-view">{{ JSON.stringify(test.config, null, 2) }}</pre>
      </div>
    </template>
  </section>
</template>

<style scoped>
.detail-header {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}
.header-info {
  display: flex;
  align-items: center;
  gap: 10px;
  flex: 1;
}
.header-info h2 {
  font-size: 18px;
}
.header-actions {
  display: flex;
  gap: 8px;
}
.tag {
  display: inline-block;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-alt, #1e293b);
  color: var(--muted, #94a3b8);
}
.tab-bar {
  display: flex;
  gap: 4px;
  border-bottom: 1px solid var(--line, #334155);
  margin-bottom: 16px;
}
.tab-bar button {
  padding: 8px 16px;
  background: none;
  border: none;
  color: var(--muted, #94a3b8);
  cursor: pointer;
  font-size: 14px;
  border-bottom: 2px solid transparent;
}
.tab-bar button.active {
  color: var(--text, #e2e8f0);
  border-bottom-color: var(--accent, #60a5fa);
}
.overview-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 12px;
}
.stat-card {
  background: var(--surface, #1e293b);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--line, #334155);
}
.stat-label {
  font-size: 13px;
  color: var(--muted, #94a3b8);
  margin-bottom: 4px;
}
.stat-value {
  font-size: 24px;
  font-weight: 700;
}
.info-panel {
  grid-column: 1 / -1;
  background: var(--surface, #1e293b);
  border-radius: 8px;
  padding: 16px;
  border: 1px solid var(--line, #334155);
}
.info-panel h4 {
  font-size: 14px;
  color: var(--muted, #94a3b8);
  margin-bottom: 10px;
}
.info-row {
  display: flex;
  justify-content: space-between;
  padding: 6px 0;
  font-size: 13px;
  border-bottom: 1px solid var(--line, #334155);
}
.info-row:last-child {
  border-bottom: none;
}
.info-row span:first-child {
  color: var(--muted, #94a3b8);
}
.results-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.result-card {
  background: var(--surface, #1e293b);
  border-radius: 8px;
  padding: 14px;
  border: 1px solid var(--line, #334155);
}
.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.result-header code {
  font-size: 13px;
}
.result-header .time {
  font-size: 12px;
  color: var(--muted, #94a3b8);
  margin-left: auto;
}
.result-error {
  color: #ef4444;
  font-size: 13px;
  padding: 8px;
  background: rgba(239, 68, 68, 0.1);
  border-radius: 4px;
  margin-bottom: 8px;
}
.result-data {
  background: var(--bg, #0f172a);
  padding: 12px;
  border-radius: 6px;
  font-size: 12px;
  overflow-x: auto;
  max-height: 300px;
  overflow-y: auto;
}
.json-view {
  background: var(--bg, #0f172a);
  padding: 16px;
  border-radius: 8px;
  font-size: 13px;
  overflow-x: auto;
  max-height: 500px;
  overflow-y: auto;
}
.empty-hint {
  text-align: center;
  padding: 40px;
  color: var(--muted, #64748b);
  font-size: 14px;
}
.monitor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(400px, 1fr));
  gap: 12px;
}
.chart-card {
  background: var(--surface, #1e293b);
  border-radius: 8px;
  border: 1px solid var(--line, #334155);
  overflow: hidden;
}
.chart-card canvas {
  width: 100%;
  height: auto;
  display: block;
  aspect-ratio: 3 / 1;
}
.monitor-legend {
  display: flex;
  gap: 16px;
  margin-top: 12px;
  flex-wrap: wrap;
}
.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: var(--muted, #94a3b8);
}
.legend-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent, #60a5fa);
}
</style>
