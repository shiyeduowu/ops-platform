<script setup lang="ts">
import { Plus, Play, Trash2, RefreshCw, Terminal, ChevronRight, Copy, Search } from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { api } from "../api";
import { bus, toast } from "../events";
import EmptyState from "../components/EmptyState.vue";
import PaginationBar from "../components/PaginationBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent, RemoteCommand } from "../types";

const commands = ref<RemoteCommand[]>([]);
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
const formType = ref("shell");
const formText = ref("");
const formTimeout = ref(60);
const formTargets = ref<string[]>([]);
const createError = ref("");
const creating = ref(false);

// 详情
const showDetail = ref(false);
const detailCommand = ref<RemoteCommand | null>(null);

const statusLabels: Record<string, string> = {
  draft: "草稿",
  pending: "等待中",
  running: "执行中",
  completed: "已完成",
  failed: "失败",
};

const onlineAgents = computed(() => agents.value.filter(a => a.status === "online"));

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const offset = (page.value - 1) * pageSize;
    const params = `?limit=${pageSize}&offset=${offset}` + (searchText.value.trim() ? `&search=${encodeURIComponent(searchText.value.trim())}` : "");
    const [cmdsData, agentsData] = await Promise.all([
      api.remoteCommands(params),
      api.agents(),
    ]);
    commands.value = cmdsData.items;
    total.value = cmdsData.total;
    agents.value = agentsData.items ?? agentsData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  formName.value = "";
  formType.value = "shell";
  formText.value = "";
  formTimeout.value = 60;
  formTargets.value = [];
  createError.value = "";
  showCreate.value = true;
}

function toggleTarget(agentId: string) {
  const idx = formTargets.value.indexOf(agentId);
  if (idx >= 0) formTargets.value.splice(idx, 1);
  else formTargets.value.push(agentId);
}

async function submitCreate() {
  if (!formName.value.trim()) { createError.value = "请输入命令名称"; return; }
  if (!formText.value.trim()) { createError.value = "请输入命令内容"; return; }
  if (formTargets.value.length === 0) { createError.value = "请选择至少一个 Agent"; return; }
  creating.value = true;
  createError.value = "";
  try {
    await api.createRemoteCommand({
      name: formName.value.trim(),
      command_type: formType.value,
      command_text: formText.value.trim(),
      timeout_seconds: formTimeout.value,
      target_agent_ids: formTargets.value,
    });
    toast("远程命令已创建");
    showCreate.value = false;
    await load();
  } catch (err) {
    createError.value = err instanceof Error ? err.message : "创建失败";
  } finally {
    creating.value = false;
  }
}

async function startCommand(id: number) {
  actionLoading.value = id;
  try {
    await api.startRemoteCommand(id);
    toast("命令已下发");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "启动失败";
  } finally {
    actionLoading.value = null;
  }
}

async function deleteCommand(id: number) {
  if (!confirm("确定删除此命令？")) return;
  actionLoading.value = id;
  try {
    await api.deleteRemoteCommand(id);
    toast("已删除");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  } finally {
    actionLoading.value = null;
  }
}

function openDetail(cmd: RemoteCommand) {
  detailCommand.value = cmd;
  showDetail.value = true;
}

function agentName(agentId: string): string {
  const a = agents.value.find(a => a.agent_id === agentId);
  return a ? a.hostname : agentId;
}

function copyText(text: string) {
  navigator.clipboard.writeText(text);
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
  if (msg.task_type === "remote_command") load();
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
        <input v-model="searchText" placeholder="搜索命令..." @keyup.enter="onSearch" />
      </label>
      <button class="btn" @click="load"><RefreshCw :size="16" /> 刷新</button>
      <button class="btn primary" @click="openCreate"><Plus :size="16" /> 新建命令</button>
    </div>

    <p v-if="error" class="alert-line">{{ error }}</p>

    <div v-if="loading" class="loading-row">加载中...</div>

    <EmptyState v-else-if="commands.length === 0" title="暂无远程命令" description="点击「新建命令」创建第一个远程命令" />

    <div v-else class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>名称</th>
            <th>类型</th>
            <th>命令</th>
            <th>状态</th>
            <th>目标数</th>
            <th>创建者</th>
            <th>创建时间</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="cmd in commands" :key="cmd.id">
            <td>
              <a class="link" @click="openDetail(cmd)">{{ cmd.name }}</a>
            </td>
            <td><span class="tag">{{ cmd.command_type }}</span></td>
            <td class="cmd-text">{{ cmd.command_text }}</td>
            <td><StatusBadge :value="cmd.status" /></td>
            <td>{{ cmd.targets.length }}</td>
            <td>{{ cmd.created_by }}</td>
            <td>{{ new Date(cmd.created_at).toLocaleString() }}</td>
            <td class="row-actions">
              <button v-if="cmd.status === 'draft' || cmd.status === 'failed'" class="btn sm" :disabled="actionLoading === cmd.id" @click="startCommand(cmd.id)">
                <Play :size="14" /> 执行
              </button>
              <button class="btn sm" @click="openDetail(cmd)">
                <ChevronRight :size="14" />
              </button>
              <button v-if="cmd.status !== 'running'" class="btn sm danger" :disabled="actionLoading === cmd.id" @click="deleteCommand(cmd.id)">
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
        <h3>新建远程命令</h3>
        <p v-if="createError" class="alert-line">{{ createError }}</p>

        <label class="field">
          <span>命令名称</span>
          <input v-model="formName" placeholder="例如：查看磁盘空间" />
        </label>

        <label class="field">
          <span>命令类型</span>
          <select v-model="formType">
            <option value="shell">Shell</option>
            <option value="powershell">PowerShell</option>
          </select>
        </label>

        <label class="field">
          <span>命令内容</span>
          <textarea v-model="formText" rows="3" placeholder="例如：df -h"></textarea>
        </label>

        <label class="field">
          <span>超时（秒）</span>
          <input v-model.number="formTimeout" type="number" min="5" max="300" />
        </label>

        <p class="hint">仅允许白名单命令：ipconfig, hostname, whoami, systeminfo, tasklist, netstat, ping, dir, df, free, uptime, ps, cat, ls 等</p>

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

    <!-- 详情弹窗 -->
    <div v-if="showDetail && detailCommand" class="modal-overlay" @click.self="showDetail = false">
      <div class="modal wide">
        <h3>{{ detailCommand.name }}</h3>
        <div class="detail-meta">
          <span class="tag">{{ detailCommand.command_type }}</span>
          <StatusBadge :value="detailCommand.status" />
          <span class="detail-cmd">{{ detailCommand.command_text }}</span>
        </div>

        <h4>执行结果</h4>
        <div v-if="detailCommand.targets.length === 0" class="hint">暂无目标</div>
        <div v-else class="results-list">
          <div v-for="t in detailCommand.targets" :key="t.id" class="result-card">
            <div class="result-header">
              <span class="result-agent">{{ agentName(t.agent_id) }}</span>
              <StatusBadge :value="t.status" />
              <span v-if="t.exit_code !== null" class="exit-code" :class="{ ok: t.exit_code === 0, fail: t.exit_code !== 0 }">
                exit: {{ t.exit_code }}
              </span>
            </div>
            <div v-if="t.stdout" class="output-block">
              <div class="output-header">
                <span>stdout</span>
                <button class="btn sm" @click="copyText(t.stdout || '')"><Copy :size="12" /></button>
              </div>
              <pre>{{ t.stdout }}</pre>
            </div>
            <div v-if="t.stderr" class="output-block stderr">
              <div class="output-header">
                <span>stderr</span>
                <button class="btn sm" @click="copyText(t.stderr || '')"><Copy :size="12" /></button>
              </div>
              <pre>{{ t.stderr }}</pre>
            </div>
            <div v-if="!t.stdout && !t.stderr && t.status === 'pending'" class="hint">等待执行...</div>
            <div v-if="!t.stdout && !t.stderr && t.status === 'running'" class="hint">执行中...</div>
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
.cmd-text {
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
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
.field input, .field select, .field textarea {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
  background: var(--bg, #0f172a);
  color: var(--text, #e2e8f0);
  font-size: 14px;
  font-family: inherit;
}
.field textarea {
  font-family: monospace;
  resize: vertical;
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
  margin-bottom: 16px;
}
.detail-cmd {
  font-family: monospace;
  font-size: 13px;
  color: var(--muted, #94a3b8);
}
.results-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.result-card {
  background: var(--bg, #0f172a);
  border-radius: 8px;
  padding: 12px;
  border: 1px solid var(--line, #334155);
}
.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.result-agent {
  font-weight: 600;
  font-size: 14px;
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
.output-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 11px;
  color: var(--muted, #64748b);
  text-transform: uppercase;
  margin-bottom: 4px;
}
.output-block pre {
  background: var(--surface, #1e293b);
  padding: 10px;
  border-radius: 6px;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 200px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
.output-block.stderr pre {
  color: #f87171;
}
</style>
