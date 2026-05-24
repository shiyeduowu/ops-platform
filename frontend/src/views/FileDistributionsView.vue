<script setup lang="ts">
import { Plus, Play, Trash2, RefreshCw, Upload, File, ChevronRight, Search } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";
import { bus, toast } from "../events";
import EmptyState from "../components/EmptyState.vue";
import PaginationBar from "../components/PaginationBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent, FileDistribution } from "../types";

const distributions = ref<FileDistribution[]>([]);
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
const formTargetPath = ref("");
const formFile = ref<File | null>(null);
const formTargets = ref<string[]>([]);
const createError = ref("");
const creating = ref(false);

// 详情
const showDetail = ref(false);
const detailDist = ref<FileDistribution | null>(null);

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
    const [distData, agentsData] = await Promise.all([
      api.fileDistributions(params),
      api.agents(),
    ]);
    distributions.value = distData.items;
    total.value = distData.total;
    agents.value = agentsData.items ?? agentsData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  formName.value = "";
  formTargetPath.value = "";
  formFile.value = null;
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
  if (!formName.value.trim()) { createError.value = "请输入任务名称"; return; }
  if (!formFile.value) { createError.value = "请选择文件"; return; }
  if (!formTargetPath.value.trim()) { createError.value = "请输入目标路径"; return; }
  if (formTargets.value.length === 0) { createError.value = "请选择至少一个 Agent"; return; }

  creating.value = true;
  createError.value = "";
  try {
    const formData = new FormData();
    formData.append("name", formName.value.trim());
    formData.append("target_path", formTargetPath.value.trim());
    formData.append("target_agent_ids", JSON.stringify(formTargets.value));
    formData.append("file", formFile.value);

    await api.createFileDistribution(formData);
    toast("文件分发已创建");
    showCreate.value = false;
    await load();
  } catch (err) {
    createError.value = err instanceof Error ? err.message : "创建失败";
  } finally {
    creating.value = false;
  }
}

async function startDist(id: number) {
  actionLoading.value = id;
  try {
    await api.startFileDistribution(id);
    toast("分发已启动");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "启动失败";
  } finally {
    actionLoading.value = null;
  }
}

async function deleteDist(id: number) {
  if (!confirm("确定删除此分发任务？")) return;
  actionLoading.value = id;
  try {
    await api.deleteFileDistribution(id);
    toast("已删除");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  } finally {
    actionLoading.value = null;
  }
}

function openDetail(dist: FileDistribution) {
  detailDist.value = dist;
  showDetail.value = true;
}

function agentName(agentId: string): string {
  const a = agents.value.find(a => a.agent_id === agentId);
  return a ? a.hostname : agentId;
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
  if (msg.task_type === "file_distribution") load();
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
        <input v-model="searchText" placeholder="搜索分发..." @keyup.enter="onSearch" />
      </label>
      <button class="btn" @click="load"><RefreshCw :size="16" /> 刷新</button>
      <button class="btn primary" @click="openCreate"><Plus :size="16" /> 新建分发</button>
    </div>

    <p v-if="error" class="alert-line">{{ error }}</p>

    <div v-if="loading" class="loading-row">加载中...</div>

    <EmptyState v-else-if="distributions.length === 0" title="暂无文件分发" description="点击「新建分发」上传文件并推送到 Agent" />

    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>文件</th>
            <th>大小</th>
            <th>目标路径</th>
            <th>状态</th>
            <th>目标数</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="d in distributions" :key="d.id">
            <td>
              <a class="link" @click="openDetail(d)">{{ d.name }}</a>
            </td>
            <td><File :size="14" style="vertical-align:middle;margin-right:4px" />{{ d.filename }}</td>
            <td>{{ formatSize(d.file_size) }}</td>
            <td class="mono">{{ d.target_path }}</td>
            <td><StatusBadge :value="d.status" /></td>
            <td>{{ d.targets.length }}</td>
            <td>{{ new Date(d.created_at).toLocaleString() }}</td>
            <td class="row-actions">
              <button v-if="d.status === 'draft' || d.status === 'failed'" class="btn sm" :disabled="actionLoading === d.id" @click="startDist(d.id)">
                <Play :size="14" /> 分发
              </button>
              <button class="btn sm" @click="openDetail(d)">
                <ChevronRight :size="14" />
              </button>
              <button v-if="d.status !== 'running'" class="btn sm danger" :disabled="actionLoading === d.id" @click="deleteDist(d.id)">
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
        <h3>新建文件分发</h3>
        <p v-if="createError" class="alert-line">{{ createError }}</p>

        <label class="field">
          <span>任务名称</span>
          <input v-model="formName" placeholder="例如：部署配置文件" />
        </label>

        <label class="field">
          <span>选择文件</span>
          <input type="file" @change="onFileChange" />
        </label>
        <p v-if="formFile" class="hint">已选: {{ formFile.name }} ({{ formatSize(formFile.size) }})</p>

        <label class="field">
          <span>Agent 目标路径</span>
          <input v-model="formTargetPath" placeholder="C:\app\config\app.conf 或 /etc/app/config.conf" />
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
    <div v-if="showDetail && detailDist" class="modal-overlay" @click.self="showDetail = false">
      <div class="modal">
        <h3>{{ detailDist.name }}</h3>
        <div class="detail-meta">
          <span>{{ detailDist.filename }}</span>
          <span class="detail-size">{{ formatSize(detailDist.file_size) }}</span>
          <StatusBadge :value="detailDist.status" />
        </div>
        <div class="detail-info">
          <span>MD5: <code>{{ detailDist.checksum_md5 }}</code></span>
          <span>目标路径: <code>{{ detailDist.target_path }}</code></span>
        </div>

        <h4>分发状态</h4>
        <div v-if="detailDist.targets.length === 0" class="hint">暂无目标</div>
        <div v-else class="target-list">
          <div v-for="t in detailDist.targets" :key="t.id" class="target-row">
            <span class="target-agent">{{ agentName(t.agent_id) }}</span>
            <StatusBadge :value="t.status" />
            <span v-if="t.error_message" class="target-error">{{ t.error_message }}</span>
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
.mono {
  font-family: monospace;
  font-size: 13px;
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
.detail-size {
  color: var(--muted, #94a3b8);
  font-size: 13px;
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
  gap: 8px;
}
.target-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  background: var(--bg, #0f172a);
  border-radius: 6px;
}
.target-agent {
  font-weight: 600;
  font-size: 14px;
  min-width: 120px;
}
.target-error {
  font-size: 12px;
  color: #f87171;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
