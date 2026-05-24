<script setup lang="ts">
import { Download, Filter, Plus, Play, Trash2, XCircle, RefreshCw, Zap } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { bus, toast } from "../events";
import { api } from "../api";
import { exportCsv } from "../export";
import EmptyState from "../components/EmptyState.vue";
import PaginationBar from "../components/PaginationBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent, StressTest } from "../types";

const router = useRouter();
const tests = ref<StressTest[]>([]);
const agents = ref<Agent[]>([]);
const loading = ref(false);
const error = ref("");
const actionLoading = ref<number | null>(null);
const statusFilter = ref("");
const typeFilter = ref("");
const page = ref(1);
const pageSize = ref(20);
const total = ref(0);
const searchText = ref("");

// 创建表单
const showCreate = ref(false);
const formName = ref("");
const formType = ref("cpu_stress");
const formConfig = ref<Record<string, any>>({});
const formTargets = ref<string[]>([]);
const createError = ref("");
const creating = ref(false);
// 调度配置
const formRecurring = ref(false);
const formIntervalSeconds = ref<number | null>(null);

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

const statusLabels: Record<string, string> = {
  draft: "草稿",
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
};

const infraTypes = ["network_bandwidth", "network_latency", "network_packet_loss", "disk_io", "cpu_stress", "memory_stress"];

const filteredTests = computed(() => tests.value);

const onlineAgents = computed(() => agents.value.filter(a => a.status === "online"));

const defaultConfigs: Record<string, Record<string, any>> = {
  network_bandwidth: { target_host: "", duration_seconds: 10, parallel_streams: 1 },
  network_latency: { target_host: "", count: 50 },
  network_packet_loss: { target_host: "", count: 100 },
  disk_io: { path: "/tmp", block_size_kb: 1024, count: 50 },
  cpu_stress: { duration_seconds: 10, threads: 0 },
  memory_stress: { target_mb: 256, duration_seconds: 10 },
  browser_automation: { url: "", steps: [], iterations: 1, timeout_ms: 30000 },
  http_api: { targets: [{ method: "GET", url: "", name: "" }], concurrency: 10, total_requests: 100, timeout_seconds: 10 },
};

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const params = new URLSearchParams();
    params.set("limit", String(pageSize.value));
    params.set("offset", String((page.value - 1) * pageSize.value));
    if (statusFilter.value) params.set("status", statusFilter.value);
    if (typeFilter.value) params.set("test_type", typeFilter.value);
    if (searchText.value.trim()) params.set("search", searchText.value.trim());

    const [testsData, agentsData] = await Promise.all([
      api.stressTests(params.toString()),
      api.agents(),
    ]);
    tests.value = testsData.items;
    total.value = testsData.total;
    agents.value = agentsData.items ?? agentsData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  formName.value = "";
  formType.value = "cpu_stress";
  formConfig.value = { ...defaultConfigs.cpu_stress };
  formTargets.value = [];
  formRecurring.value = false;
  formIntervalSeconds.value = null;
  createError.value = "";
  showCreate.value = true;
}

function onTypeChange() {
  formConfig.value = { ...defaultConfigs[formType.value] };
}

function toggleTarget(agentId: string) {
  const idx = formTargets.value.indexOf(agentId);
  if (idx >= 0) formTargets.value.splice(idx, 1);
  else formTargets.value.push(agentId);
}

async function submitCreate() {
  if (!formName.value.trim()) { createError.value = "请输入测试名称"; return; }
  if (formTargets.value.length === 0) { createError.value = "请选择至少一个 Agent"; return; }
  creating.value = true;
  createError.value = "";
  try {
    await api.createStressTest({
      name: formName.value.trim(),
      test_type: formType.value,
      config: formConfig.value,
      target_agent_ids: formTargets.value,
      is_recurring: formRecurring.value,
      schedule_interval_seconds: formRecurring.value ? formIntervalSeconds.value : null,
    });
    toast("压力测试已创建");
    showCreate.value = false;
    await load();
  } catch (err) {
    createError.value = err instanceof Error ? err.message : "创建失败";
  } finally {
    creating.value = false;
  }
}

async function startTest(id: number) {
  actionLoading.value = id;
  try {
    await api.startStressTest(id);
    toast("压力测试已启动");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "启动失败";
  } finally {
    actionLoading.value = null;
  }
}

async function cancelTest(id: number) {
  actionLoading.value = id;
  try {
    await api.cancelStressTest(id);
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "取消失败";
  } finally {
    actionLoading.value = null;
  }
}

async function deleteTest(id: number) {
  if (!confirm("确定删除此测试？")) return;
  actionLoading.value = id;
  try {
    await api.deleteStressTest(id);
    toast("已删除");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  } finally {
    actionLoading.value = null;
  }
}

function onTaskCompleted(msg: any) {
  if (msg.task_type === "stress_test") load();
}

function exportData() {
  exportCsv(
    "stress_tests.csv",
    ["name", "test_type", "status", "created_by", "created_at"],
    tests.value.map((t) => [t.name, testTypeLabels[t.test_type] || t.test_type, t.status, t.created_by, new Date(t.created_at).toLocaleString()]),
  );
}

onMounted(() => {
  load();
  bus.on("task_completed", onTaskCompleted);
});

onUnmounted(() => {
  bus.off("task_completed", onTaskCompleted);
});
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <input v-model="searchText" placeholder="搜索测试名称..." class="search-input" @keyup.enter="load" />
      <label class="select-box">
        <Filter :size="17" />
        <select v-model="statusFilter" @change="page=1; load()">
          <option value="">全部状态</option>
          <option value="draft">草稿</option>
          <option value="pending">等待中</option>
          <option value="running">运行中</option>
          <option value="completed">已完成</option>
          <option value="failed">失败</option>
          <option value="cancelled">已取消</option>
        </select>
      </label>
      <label class="select-box">
        <select v-model="typeFilter" @change="page=1; load()">
          <option value="">全部类型</option>
          <option v-for="(label, key) in testTypeLabels" :key="key" :value="key">{{ label }}</option>
        </select>
      </label>
      <div style="flex:1"></div>
      <button class="btn" @click="load"><RefreshCw :size="16" /> 刷新</button>
      <button class="btn" @click="exportData"><Download :size="16" /> 导出</button>
      <button class="btn primary" @click="openCreate"><Plus :size="16" /> 新建测试</button>
    </div>

    <p v-if="error" class="alert-line">{{ error }}</p>

    <div v-if="loading" class="loading-row">加载中...</div>

    <EmptyState v-else-if="filteredTests.length === 0" title="暂无压力测试" description="点击「新建测试」创建第一个压测任务" />

    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>状态</th>
            <th>目标数</th>
            <th>创建者</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="t in filteredTests" :key="t.id">
            <td>
              <a class="link" @click="router.push(`/stress-tests/${t.id}`)">{{ t.name }}</a>
            </td>
            <td><span class="tag">{{ testTypeLabels[t.test_type] || t.test_type }}</span></td>
            <td><StatusBadge :value="t.status" /></td>
            <td>{{ t.targets.length }}</td>
            <td>{{ t.created_by }}</td>
            <td>{{ new Date(t.created_at).toLocaleString() }}</td>
            <td class="row-actions">
              <button v-if="t.status === 'draft' || t.status === 'failed'" class="btn sm" :disabled="actionLoading === t.id" @click="startTest(t.id)">
                <Play :size="14" /> 启动
              </button>
              <button v-if="t.status === 'pending' || t.status === 'running'" class="btn sm warn" :disabled="actionLoading === t.id" @click="cancelTest(t.id)">
                <XCircle :size="14" /> 取消
              </button>
              <button v-if="t.status !== 'running'" class="btn sm danger" :disabled="actionLoading === t.id" @click="deleteTest(t.id)">
                <Trash2 :size="14" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
      <PaginationBar :total="total" :page="page" :page-size="pageSize" @update:page="p => { page = p; load(); }" />
    </div>

    <!-- 创建弹窗 -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h3>新建压力测试</h3>
        <p v-if="createError" class="alert-line">{{ createError }}</p>

        <label class="field">
          <span>测试名称</span>
          <input v-model="formName" placeholder="例如：CPU 压力测试" />
        </label>

        <label class="field">
          <span>测试类型</span>
          <select v-model="formType" @change="onTypeChange">
            <option v-for="(label, key) in testTypeLabels" :key="key" :value="key">{{ label }}</option>
          </select>
        </label>

        <!-- 动态配置表单 -->
        <div class="config-form">
          <h4>测试配置</h4>

          <template v-if="infraTypes.includes(formType)">
            <label v-if="formType.startsWith('network')" class="field">
              <span>目标主机</span>
              <input v-model="formConfig.target_host" placeholder="192.168.1.100" />
            </label>
            <label v-if="formType === 'network_bandwidth'" class="field">
              <span>持续时间（秒）</span>
              <input v-model.number="formConfig.duration_seconds" type="number" min="5" max="60" />
            </label>
            <label v-if="formType === 'network_latency'" class="field">
              <span>Ping 次数</span>
              <input v-model.number="formConfig.count" type="number" min="10" max="500" />
            </label>
            <label v-if="formType === 'disk_io'" class="field">
              <span>测试路径</span>
              <input v-model="formConfig.path" placeholder="/tmp" />
            </label>
            <label v-if="formType === 'disk_io'" class="field">
              <span>块大小 (KB)</span>
              <input v-model.number="formConfig.block_size_kb" type="number" min="64" max="16384" />
            </label>
            <label v-if="formType === 'cpu_stress' || formType === 'memory_stress'" class="field">
              <span>持续时间（秒）</span>
              <input v-model.number="formConfig.duration_seconds" type="number" min="5" max="300" />
            </label>
            <label v-if="formType === 'memory_stress'" class="field">
              <span>目标内存 (MB)</span>
              <input v-model.number="formConfig.target_mb" type="number" min="64" max="8192" />
            </label>
          </template>

          <template v-if="formType === 'browser_automation'">
            <label class="field">
              <span>入口 URL</span>
              <input v-model="formConfig.url" placeholder="https://example.com/login" />
            </label>
            <label class="field">
              <span>迭代次数</span>
              <input v-model.number="formConfig.iterations" type="number" min="1" max="50" />
            </label>
            <label class="field">
              <span>超时 (ms)</span>
              <input v-model.number="formConfig.timeout_ms" type="number" min="5000" max="120000" />
            </label>
            <p class="hint">浏览器步骤需在详情页中配置（navigate/click/input/wait/assert_text/screenshot）</p>
          </template>

          <template v-if="formType === 'http_api'">
            <div v-for="(t, idx) in formConfig.targets" :key="idx" class="http-target-item">
              <h5>目标 {{ (idx as number) + 1 }}</h5>
              <label class="field">
                <span>名称</span>
                <input v-model="t.name" placeholder="获取用户列表" />
              </label>
              <label class="field">
                <span>方法</span>
                <select v-model="t.method">
                  <option>GET</option><option>POST</option><option>PUT</option><option>DELETE</option><option>PATCH</option>
                </select>
              </label>
              <label class="field">
                <span>URL</span>
                <input v-model="t.url" placeholder="https://api.example.com/users" />
              </label>
              <button v-if="formConfig.targets.length > 1" class="btn sm danger" @click="formConfig.targets.splice(idx, 1)">删除</button>
            </div>
            <button class="btn sm" @click="formConfig.targets.push({ method: 'GET', url: '', name: '' })">+ 添加目标</button>
            <label class="field">
              <span>并发数</span>
              <input v-model.number="formConfig.concurrency" type="number" min="1" max="100" />
            </label>
            <label class="field">
              <span>总请求数</span>
              <input v-model.number="formConfig.total_requests" type="number" min="10" max="10000" />
            </label>
            <label class="field">
              <span>超时（秒）</span>
              <input v-model.number="formConfig.timeout_seconds" type="number" min="1" max="60" />
            </label>
          </template>
        </div>

        <!-- 调度配置 -->
        <div class="schedule-section">
          <h4>调度配置</h4>
          <label class="check-field">
            <input type="checkbox" v-model="formRecurring" />
            <span>定时循环执行</span>
          </label>
          <template v-if="formRecurring">
            <label class="field">
              <span>执行间隔（秒）</span>
              <input v-model.number="formIntervalSeconds" type="number" min="60" max="86400" placeholder="3600 = 每小时" />
            </label>
            <p class="hint">测试完成后自动按间隔创建下一次测试</p>
          </template>
        </div>

        <!-- Agent 选择 -->
        <div class="agent-select">
          <h4>选择目标 Agent</h4>
          <p v-if="onlineAgents.length === 0" class="hint">暂无在线 Agent</p>
          <div v-else class="agent-grid">
            <label v-for="a in onlineAgents" :key="a.agent_id" class="agent-check" :class="{ selected: formTargets.includes(a.agent_id) }">
              <input type="checkbox" :checked="formTargets.includes(a.agent_id)" @change="toggleTarget(a.agent_id)" />
              <span class="agent-hostname">{{ a.hostname }}</span>
              <span class="agent-ip">{{ a.ip }}</span>
            </label>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn" @click="showCreate = false">取消</button>
          <button class="btn primary" :disabled="creating" @click="submitCreate">
            {{ creating ? "创建中..." : "创建" }}
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.search-input {
  padding: 6px 10px;
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
  background: var(--bg, #0f172a);
  color: var(--text, #e2e8f0);
  font-size: 13px;
  width: 200px;
}
.search-input::placeholder {
  color: var(--muted, #64748b);
}
.tag {
  display: inline-block;
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--surface-alt, #1e293b);
  color: var(--muted, #94a3b8);
}
.row-actions {
  display: flex;
  gap: 6px;
  white-space: nowrap;
}
.link {
  color: var(--accent, #60a5fa);
  cursor: pointer;
}
.link:hover {
  text-decoration: underline;
}
.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
}
.modal {
  background: var(--surface, #1e293b);
  border-radius: 12px;
  padding: 24px;
  width: 560px;
  max-height: 85vh;
  overflow-y: auto;
  border: 1px solid var(--line, #334155);
}
.modal h3 {
  margin-bottom: 16px;
  font-size: 18px;
}
.modal h4 {
  font-size: 14px;
  color: var(--muted, #94a3b8);
  margin: 16px 0 8px;
}
.field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}
.field span {
  font-size: 13px;
  color: var(--muted, #94a3b8);
}
.field input, .field select {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
  background: var(--bg, #0f172a);
  color: var(--text, #e2e8f0);
  font-size: 14px;
}
.hint {
  font-size: 12px;
  color: var(--muted, #64748b);
  margin: 4px 0;
}
.agent-select {
  margin-top: 16px;
}
.agent-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(200px, 1fr));
  gap: 8px;
  margin-top: 8px;
}
.agent-check {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
  cursor: pointer;
  font-size: 13px;
}
.agent-check.selected {
  border-color: var(--accent, #60a5fa);
  background: rgba(96, 165, 250, 0.1);
}
.agent-hostname {
  font-weight: 500;
}
.agent-ip {
  color: var(--muted, #94a3b8);
  font-size: 12px;
}
.http-target-item {
  padding: 12px;
  margin-bottom: 10px;
  background: var(--bg, #0f172a);
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
}
.http-target-item h5 {
  font-size: 13px;
  color: var(--muted, #94a3b8);
  margin-bottom: 8px;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
.schedule-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--line, #334155);
}
.schedule-section h4 {
  font-size: 14px;
  color: var(--muted, #94a3b8);
  margin-bottom: 8px;
}
.check-field {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  cursor: pointer;
  margin-bottom: 8px;
}
</style>
