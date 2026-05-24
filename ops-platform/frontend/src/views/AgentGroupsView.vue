<script setup lang="ts">
import { Plus, Trash2, Edit, Users, UserPlus, X, RefreshCw, Palette } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { api } from "../api";
import { toast } from "../events";
import EmptyState from "../components/EmptyState.vue";
import type { Agent, AgentGroup } from "../types";

const groups = ref<AgentGroup[]>([]);
const agents = ref<Agent[]>([]);
const loading = ref(false);
const error = ref("");

// 创建/编辑表单
const showModal = ref(false);
const editingId = ref<number | null>(null);
const formName = ref("");
const formDescription = ref("");
const formColor = ref("#60a5fa");
const formError = ref("");
const saving = ref(false);

// 成员管理
const showMembers = ref(false);
const membersGroupId = ref<number | null>(null);
const membersGroupName = ref("");
const groupMembers = ref<string[]>([]);
const addAgentId = ref("");
const memberError = ref("");

const presetColors = [
  "#60a5fa", "#34d399", "#f472b6", "#a78bfa",
  "#fbbf24", "#fb923c", "#f87171", "#38bdf8",
];

const availableAgents = computed(() => {
  const memberSet = new Set(groupMembers.value);
  return agents.value.filter(a => !memberSet.has(a.agent_id));
});

const groupMap = computed(() => {
  const m = new Map<string, string[]>();
  for (const g of groups.value) {
    for (const mem of g.members) {
      const list = m.get(mem.agent_id) || [];
      list.push(g.name);
      m.set(mem.agent_id, list);
    }
  }
  return m;
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [groupsData, agentsData] = await Promise.all([
      api.agentGroups(),
      api.agents(),
    ]);
    groups.value = groupsData.items ?? groupsData;
    agents.value = agentsData.items ?? agentsData;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function openCreate() {
  editingId.value = null;
  formName.value = "";
  formDescription.value = "";
  formColor.value = "#60a5fa";
  formError.value = "";
  showModal.value = true;
}

function openEdit(group: AgentGroup) {
  editingId.value = group.id;
  formName.value = group.name;
  formDescription.value = group.description || "";
  formColor.value = group.color;
  formError.value = "";
  showModal.value = true;
}

async function submitForm() {
  if (!formName.value.trim()) {
    formError.value = "请输入分组名称";
    return;
  }
  saving.value = true;
  formError.value = "";
  try {
    const payload = {
      name: formName.value.trim(),
      description: formDescription.value.trim() || undefined,
      color: formColor.value,
    };
    if (editingId.value) {
      await api.updateAgentGroup(editingId.value, payload);
    } else {
      await api.createAgentGroup(payload);
    }
    toast(editingId.value ? "分组已更新" : "分组已创建");
    showModal.value = false;
    await load();
  } catch (err) {
    formError.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function deleteGroup(id: number) {
  if (!confirm("确定删除此分组？")) return;
  try {
    await api.deleteAgentGroup(id);
    toast("分组已删除");
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  }
}

function openMembers(group: AgentGroup) {
  membersGroupId.value = group.id;
  membersGroupName.value = group.name;
  groupMembers.value = group.members.map(m => m.agent_id);
  addAgentId.value = "";
  memberError.value = "";
  showMembers.value = true;
}

async function addMember() {
  if (!addAgentId.value || !membersGroupId.value) return;
  memberError.value = "";
  try {
    const result = await api.addGroupMembers(membersGroupId.value, [addAgentId.value]);
    groupMembers.value = result.members.map(m => m.agent_id);
    // 更新列表中的数据
    const idx = groups.value.findIndex(g => g.id === membersGroupId.value);
    if (idx >= 0) groups.value[idx] = result;
    addAgentId.value = "";
  } catch (err) {
    memberError.value = err instanceof Error ? err.message : "添加失败";
  }
}

async function removeMember(agentId: string) {
  if (!membersGroupId.value) return;
  memberError.value = "";
  try {
    await api.removeGroupMember(membersGroupId.value, agentId);
    groupMembers.value = groupMembers.value.filter(id => id !== agentId);
    // 更新列表中的数据
    const idx = groups.value.findIndex(g => g.id === membersGroupId.value);
    if (idx >= 0) {
      groups.value[idx] = {
        ...groups.value[idx],
        members: groups.value[idx].members.filter(m => m.agent_id !== agentId),
      };
    }
  } catch (err) {
    memberError.value = err instanceof Error ? err.message : "移除失败";
  }
}

function agentName(agentId: string): string {
  const a = agents.value.find(a => a.agent_id === agentId);
  return a ? a.hostname : agentId;
}

function agentIp(agentId: string): string {
  const a = agents.value.find(a => a.agent_id === agentId);
  return a?.ip || "";
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <div style="flex:1"></div>
      <button class="btn" @click="load"><RefreshCw :size="16" /> 刷新</button>
      <button class="btn primary" @click="openCreate"><Plus :size="16" /> 新建分组</button>
    </div>

    <p v-if="error" class="alert-line">{{ error }}</p>

    <div v-if="loading" class="loading-row">加载中...</div>

    <EmptyState v-else-if="groups.length === 0" title="暂无分组" description="点击「新建分组」创建第一个 Agent 分组" />

    <div v-else class="groups-grid">
      <div v-for="g in groups" :key="g.id" class="group-card" :style="{ borderColor: g.color }">
        <div class="group-header">
          <div class="group-title">
            <span class="color-dot" :style="{ background: g.color }"></span>
            <h3>{{ g.name }}</h3>
          </div>
          <div class="group-actions">
            <button class="btn sm" title="管理成员" @click="openMembers(g)">
              <UserPlus :size="14" />
            </button>
            <button class="btn sm" title="编辑" @click="openEdit(g)">
              <Edit :size="14" />
            </button>
            <button class="btn sm danger" title="删除" @click="deleteGroup(g.id)">
              <Trash2 :size="14" />
            </button>
          </div>
        </div>
        <p v-if="g.description" class="group-desc">{{ g.description }}</p>
        <div class="group-meta">
          <Users :size="14" />
          <span>{{ g.members.length }} 个成员</span>
        </div>
        <div v-if="g.members.length > 0" class="member-tags">
          <span v-for="m in g.members.slice(0, 6)" :key="m.agent_id" class="member-tag">
            {{ agentName(m.agent_id) }}
          </span>
          <span v-if="g.members.length > 6" class="member-tag more">+{{ g.members.length - 6 }}</span>
        </div>
      </div>
    </div>

    <!-- 创建/编辑弹窗 -->
    <div v-if="showModal" class="modal-overlay" @click.self="showModal = false">
      <div class="modal">
        <h3>{{ editingId ? "编辑分组" : "新建分组" }}</h3>
        <p v-if="formError" class="alert-line">{{ formError }}</p>

        <label class="field">
          <span>分组名称</span>
          <input v-model="formName" placeholder="例如：生产环境" />
        </label>

        <label class="field">
          <span>描述</span>
          <input v-model="formDescription" placeholder="可选" />
        </label>

        <label class="field">
          <span>颜色</span>
          <div class="color-picker">
            <span
              v-for="c in presetColors"
              :key="c"
              class="color-swatch"
              :class="{ active: formColor === c }"
              :style="{ background: c }"
              @click="formColor = c"
            ></span>
            <input v-model="formColor" type="color" class="color-input" />
          </div>
        </label>

        <div class="modal-actions">
          <button class="btn" @click="showModal = false">取消</button>
          <button class="btn primary" :disabled="saving" @click="submitForm">
            {{ saving ? "保存中..." : "保存" }}
          </button>
        </div>
      </div>
    </div>

    <!-- 成员管理弹窗 -->
    <div v-if="showMembers" class="modal-overlay" @click.self="showMembers = false">
      <div class="modal">
        <h3>管理成员 — {{ membersGroupName }}</h3>
        <p v-if="memberError" class="alert-line">{{ memberError }}</p>

        <div class="add-member-row">
          <select v-model="addAgentId" class="add-select">
            <option value="">选择 Agent</option>
            <option v-for="a in availableAgents" :key="a.agent_id" :value="a.agent_id">
              {{ a.hostname }} ({{ a.ip || a.agent_id }})
            </option>
          </select>
          <button class="btn primary sm" :disabled="!addAgentId" @click="addMember">
            <UserPlus :size="14" /> 添加
          </button>
        </div>

        <div v-if="groupMembers.length === 0" class="hint" style="margin:16px 0;">暂无成员</div>

        <div v-else class="member-list">
          <div v-for="aid in groupMembers" :key="aid" class="member-row">
            <div class="member-info">
              <span class="member-hostname">{{ agentName(aid) }}</span>
              <span class="member-ip">{{ agentIp(aid) }}</span>
            </div>
            <button class="btn sm danger" @click="removeMember(aid)">
              <X :size="14" />
            </button>
          </div>
        </div>

        <div class="modal-actions">
          <button class="btn" @click="showMembers = false">关闭</button>
        </div>
      </div>
    </div>
  </section>
</template>

<style scoped>
.groups-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}
.group-card {
  background: var(--surface, #1e293b);
  border-radius: 10px;
  border: 1px solid var(--line, #334155);
  border-left: 4px solid;
  padding: 16px;
}
.group-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.group-title {
  display: flex;
  align-items: center;
  gap: 8px;
}
.group-title h3 {
  font-size: 16px;
  margin: 0;
}
.color-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
}
.group-actions {
  display: flex;
  gap: 4px;
}
.group-desc {
  font-size: 13px;
  color: var(--muted, #94a3b8);
  margin: 8px 0 0;
}
.group-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--muted, #94a3b8);
  margin-top: 10px;
}
.member-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 10px;
}
.member-tag {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 4px;
  background: var(--bg, #0f172a);
  color: var(--muted, #94a3b8);
}
.member-tag.more {
  background: var(--surface-alt, #334155);
  color: var(--text, #e2e8f0);
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
  width: 480px;
  max-height: 85vh;
  overflow-y: auto;
  border: 1px solid var(--line, #334155);
}
.modal h3 {
  margin-bottom: 16px;
  font-size: 18px;
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
.field input {
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
  background: var(--bg, #0f172a);
  color: var(--text, #e2e8f0);
  font-size: 14px;
}
.color-picker {
  display: flex;
  gap: 8px;
  align-items: center;
}
.color-swatch {
  width: 28px;
  height: 28px;
  border-radius: 6px;
  cursor: pointer;
  border: 2px solid transparent;
  transition: border-color 0.15s;
}
.color-swatch.active {
  border-color: var(--text, #e2e8f0);
}
.color-input {
  width: 36px;
  height: 28px;
  padding: 0;
  border: none;
  cursor: pointer;
}
.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 20px;
}
.hint {
  font-size: 12px;
  color: var(--muted, #64748b);
}
.add-member-row {
  display: flex;
  gap: 8px;
  margin-bottom: 16px;
}
.add-select {
  flex: 1;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--line, #334155);
  background: var(--bg, #0f172a);
  color: var(--text, #e2e8f0);
  font-size: 14px;
}
.member-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.member-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 10px;
  background: var(--bg, #0f172a);
  border-radius: 6px;
}
.member-info {
  display: flex;
  align-items: center;
  gap: 8px;
}
.member-hostname {
  font-weight: 500;
  font-size: 13px;
}
.member-ip {
  color: var(--muted, #94a3b8);
  font-size: 12px;
}
</style>
