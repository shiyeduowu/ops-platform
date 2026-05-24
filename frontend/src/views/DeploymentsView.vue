<script setup lang="ts">
import { Plus, Play, Trash2, RefreshCw, Package, ChevronRight, Search } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";
import { bus, toast } from "../events";
import EmptyState from "../components/EmptyState.vue";
import PaginationBar from "../components/PaginationBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent, SoftwareDeployment } from "../types";

const deployments = ref<SoftwareDeployment[]>([]);
const agents = ref<Agent[]>([]);
const loading = ref(false);
const error = ref("");
const actionLoading = ref<number | null>(null);

// 分页 & 搜索
const page = ref(1);
const pageSize = 20;
const total = ref(0);
const searchText = ref("");

// 创建表单
const showCreate = ref(false);
const formName = ref("");
const formSoftware = ref("");
const formVersion = ref("");
const formFile = ref<File | null>(null);
const formInstallCmd = ref("");
const formInstallArgs = ref("");
const formTimeout = ref(300);
const formTargets = ref<string[]>([]);
const createError = ref("");
const creating = ref(false);

// 详情
const showDetail = ref(false);
const detailDep = ref<SoftwareDeployment | null>(null);

const onlineAgents = computed(() => agents.value.filter(a => a.status === "online"));

function formatSize(bytes: number): string {
  if (bytes < 1024) return bytes + " B";
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
  return (bytes / 1024 / 1024).toFixed(1) + " MB";
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const offset = (page.value - 1) * pageSize;
    const params = `?limit=${pageSize}&offset=${offset}` + (searchText.value.trim() ? `&search=${encodeURIComponent(searchText.value.trim())}` : "");
    const [depData, agentsData] = await Promise.all([
      api.deployments(params),
      api.agents(),
    ]);
    deployments.value = depData.items;
    total.value = depData.total;
    agents.value = agentsData.items ?? agentsData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  formName.value = "";
  formSoftware.value = "";
  formVersion.value = "";
  formFile.value = null;
  formInstallCmd.value = "";
  formInstallArgs.value = "";
  formTimeout.value = 300;
  formTargets.value = [];
  createError.value = "";
  showCreate.value = true;
}

function onFileChange(e: Event) {
  const input = e.target as HTMLInputElement;
  formFile.value = input.files?.[0] || null;
}

function toggleTarget(agentId: string) {
  const idx = formTargets.value.indexOf(agentId);
  if (idx >= 0) formTargets.value.splice(idx, 1);
  else formTargets.value.push(agentId);
}

async function submitCreate() {
  if (!formName.value.trim()) { createError.value = "请输入部署名称"; return; }
  if (!formSoftware.value.trim()) { createError.value = "请输入软件名称"; return; }
  if (!formVersion.value.trim()) { createError.value = "请输入版本号"; return; }
  if (!formFile.value) { createError.value = "请选择安装包"; return; }
  if (!formInstallCmd.value.trim()) { createError.value = "请输入安装命令"; return; }
  if (formTargets.value.length === 0) { createError.value = "请选择至少一个 Agent"; return; }

  creating.value = true;
  createError.value = "";
  try {
    const formData = new FormData();
    formData.append("name", formName.value.trim());
    formData.append("software_name", formSoftware.value.trim());
    formData.append("version", formVersion.value.trim());
    formData.append("install_command", formInstallCmd.value.trim());
    formData.append("install_args", formInstallArgs.value.trim());
    formData.append("timeout_seconds", String(formTimeout.value));
    formData.append("target_agent_ids", JSON.stringify(formTargets.value));
    formData.append("file", formFile.value);

    await api.createDeployment(formData);
    toast("部署任务已创建");
    showCreate.value = false;
    await load();
  } catch (err) {
    createError.value = err instanceof Error ? err.message : "创建失败";
  } finally {
    creating.value = false;
  }
}

async function startDep(id: number) {
  actionLoading.value = id;
  try {
    await api.startDeployment(id);
    toast("部署已启动");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "启动失败";
  } finally {
    actionLoading.value = null;
  }
}

async function deleteDep(id: number) {
  if (!confirm("确定删除此部署任务？")) return;
  actionLoading.value = id;
  try {
    await api.deleteDeployment(id);
    toast("已删除");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  } finally {
    actionLoading.value = null;
  }
}

function openDetail(dep: SoftwareDeployment) {
  detailDep.value = dep;
  showDetail.value = true;
}

function agentName(agentId: string): string {
  const a = agents.value.find(a => a.agent_id === agentId);
  return a ? a.hostname : agentId;
}

function statusColor(fileStatus: string, installStatus: string): string {
  if (installStatus === "completed") return "#22c55e";
  if (installStatus === "failed" || fileStatus === "failed") return "#ef4444";
  if (installStatus === "running" || fileStatus === "downloading") return "#f59e0b";
  return "#64748b";
}

function onPageChange(p: number) {
  page.value = p;
  load();
}

function onSearch() {
  page.value = 1;
  load();
}

function onTaskCompleted(msg: any) {
  if (msg.task_type === "software_deployment") load();
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
      <label class="search-box">
        <Search :size="17" />
        <input v-model="searchText" placeholder="搜索部署..." @keyup.enter="onSearch" />
      </label>
      <button class="btn" @click="load"><RefreshCw :size="16" /> 刷新</button>
      <button class="btn primary" @click="openCreate"><Plus :size="16" /> 新建部署</button>
    </div>

    <p v-if="error" class="alert-line">{{ error }}</p>

    <div v-if="loading" class="loading-row">加载中...</div>

    <EmptyState v-else-if="deployments.length === 0" title="暂无部署任务" description="点击「新建部署」上传安装包并推送到 Agent" />

    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>软件</th>
            <th>版本</th>
            <th>状态</th>
            <th>目标数</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in deployments" :key="d.id">
            <td>
              <a class="link" @click="openDetail(d)">{{ d.name }}</a>
            </td>
            <td>{{ d.software_name }}</td>
            <td><span class="tag">{{ d.version }}</span></td>
            <td><StatusBadge :value="d.status" /></td>
            <td>{{ d.targets.length }}</td>
            <td>{{ new Date(d.created_at).toLocaleString() }}</td>
            <td class="row-actions">
              <button v-if="d.status === 'draft' || d.status === 'failed'" class="btn sm" :disabled="actionLoading === d.id" @click="startDep(d.id)">
                <Play :size="14" /> 部署
              </button>
              <button class="btn sm" @click="openDetail(d)">
                <ChevronRight :size="14" />
              </button>
              <button v-if="d.status !== 'running'" class="btn sm danger" :disabled="actionLoading === d.id" @click="deleteDep(d.id)">
                <Trash2 :size="14" />
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <PaginationBar v-if="total > pageSize" :page="page" :page-size="pageSize" :total="total" @update:page="onPageChange" />

    <!-- 创建弹窗 -->
    <div v-if="showCreate" class="modal-overlay" @click.self="showCreate = false">
      <div class="modal">
        <h3>新建软件部署</h3>
        <p v-if="createError" class="alert-line">{{ createError }}</p>

        <label class="field">
          <span>部署名称</span>
          <input v-model="formName" placeholder="例如：部署 Nginx 1.25" />
        </label>

        <div class="field-row">
          <label class="field">
            <span>软件名称</span>
            <input v-model="formSoftware" placeholder="Nginx" />
          </label>
          <label class="field">
            <span>版本</span>
            <input v-model="formVersion" placeholder="1.25.3" />
          </label>
        </div>

        <label class="field">
          <span>安装包</span>
          <input type="file" @change="onFileChange" />
        </label>
        <p v-if="formFile" class="hint">已选: {{ formFile.name }} ({{ formatSize(formFile.size) }})</p>

        <label class="field">
          <span>安装命令</span>
          <input v-model="formInstallCmd" placeholder="msiexec /i {installer} /quiet /norestart" />
        </label>
        <p class="hint">使用 {installer} 作为安装包路径的占位符</p>

        <label class="field">
          <span>安装参数</span>
          <input v-model="formInstallArgs" placeholder="INSTALLDIR=C:\Apps\Nginx（可选）" />
        </label>

        <label class="field">
          <span>超时（秒）</span>
          <input v-model.number="formTimeout" type="number" min="60" max="1800" />
        </label>

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
            {{ creating ? "上传中..." : "创建" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 详情弹窗 -->
    <div v-if="showDetail && detailDep" class="modal-overlay" @click.self="showDetail = false">
      <div class="modal wide">
        <h3>{{ detailDep.name }}</h3>
        <div class="detail-meta">
          <span>{{ detailDep.software_name }} v{{ detailDep.version }}</span>
          <StatusBadge :value="detailDep.status" />
        </div>
        <div class="detail-info">
          <span>安装包: {{ detailDep.installer_filename }} ({{ formatSize(detailDep.file_size) }})</span>
          <span>安装命令: <code>{{ detailDep.install_command }}</code></span>
        </div>

        <h4>部署状态</h4>
        <div v-if="detailDep.targets.length === 0" class="hint">暂无目标</div>
        <div v-else class="target-list">
          <div v-for="t in detailDep.targets" :key="t.id" class="target-card">
            <div class="target-header">
              <span class="target-agent">{{ agentName(t.agent_id) }}</span>
              <span class="phase-badge" :style="{ background: statusColor(t.file_status, t.install_status) }">
                文件: {{ t.file_status }}
              </span>
              <span class="phase-badge" :style="{ background: statusColor(t.file_status, t.install_status) }">
                安装: {{ t.install_status }}
              </span>
              <span v-if="t.exit_code !== null" class="exit-code" :class="{ ok: t.exit_code === 0, fail: t.exit_code !== 0 }">
                exit: {{ t.exit_code }}
              </span>
            </div>
            <div v-if="t.stdout" class="output-block">
              <span class="output-label">stdout</span>
              <pre>{{ t.stdout }}</pre>
            </div>
            <div v-if="t.stderr" class="output-block stderr">
              <span class="output-label">stderr</span>
              <pre>{{ t.stderr }}</pre>
            </div>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn" @click="showDetail = false">关闭</button>
        </div>
      </div>
    </div>
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
.modal.wide {
  width: 720px;
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
.field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
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
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}
.detail-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 13px;
  color: var(--muted, #94a3b8);
}
.detail-info code {
  font-family: monospace;
  font-size: 12px;
}
.target-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.target-card {
  background: var(--bg, #0f172a);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--line, #334155);
}
.target-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.target-agent {
  font-weight: 600;
  font-size: 14px;
  min-width: 100px;
}
.phase-badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  color: #fff;
}
.exit-code {
  font-size: 12px;
  font-family: monospace;
  padding: 2px 6px;
  border-radius: 4px;
}
.exit-code.ok {
  background: rgba(34, 197, 94, 0.15);
  color: #22c55e;
}
.exit-code.fail {
  background: rgba(239, 68, 68, 0.15);
  color: #ef4444;
}
.output-block {
  margin-top: 6px;
}
.output-label {
  font-size: 11px;
  color: var(--muted, #64748b);
  text-transform: uppercase;
}
.output-block pre {
  background: var(--surface, #1e293b);
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 150px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin-top: 4px;
}
.output-block.stderr pre {
  color: #f87171;
}
</style>
