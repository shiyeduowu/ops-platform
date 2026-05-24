<script setup lang="ts">
import {
  Bell,
  Plus,
  RefreshCw,
  Send,
  Trash2,
  ToggleLeft,
  ToggleRight,
  MessageCircle,
  Mail,
  Globe,
  Webhook,
  FileText,
  CheckCircle,
  XCircle,
  Clock
} from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { api } from "../api";
import EmptyState from "../components/EmptyState.vue";
import type { NotificationChannel, ForwardingLog } from "../types";

const activeTab = ref<"channels" | "logs">("channels");
const channels = ref<NotificationChannel[]>([]);
const forwardingLogs = ref<ForwardingLog[]>([]);
const loading = ref(false);
const error = ref("");
const showCreate = ref(false);
const testingId = ref<number | null>(null);
const testResult = ref("");
const logHours = ref(24);

const channelTypes = [
  { value: "dingtalk", label: "钉钉", icon: MessageCircle, color: "#0089FF" },
  { value: "wecom", label: "企业微信", icon: MessageCircle, color: "#07C160" },
  { value: "feishu", label: "飞书", icon: MessageCircle, color: "#3370FF" },
  { value: "email", label: "邮件", icon: Mail, color: "#FF6A00" },
  { value: "webhook", label: "Webhook", icon: Webhook, color: "#8B5CF6" },
];

const form = ref({
  name: "",
  channel_type: "dingtalk",
  config: {} as Record<string, unknown>,
  enabled: true,
});

function getChannelInfo(type: string) {
  return channelTypes.find(c => c.value === type) || channelTypes[0];
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    channels.value = await api.notificationChannels();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadLogs() {
  loading.value = true;
  error.value = "";
  try {
    forwardingLogs.value = await api.forwardingLogs(`?hours=${logHours.value}`);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function switchTab(tab: "channels" | "logs") {
  activeTab.value = tab;
  if (tab === "logs") loadLogs();
}

async function createChannel() {
  try {
    await api.createNotificationChannel(form.value);
    showCreate.value = false;
    form.value = { name: "", channel_type: "dingtalk", config: {}, enabled: true };
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "创建失败";
  }
}

async function toggleChannel(channel: NotificationChannel) {
  try {
    await api.updateNotificationChannel(channel.id, { enabled: !channel.enabled });
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "更新失败";
  }
}

async function deleteChannel(id: number) {
  if (!confirm("确定删除此通知渠道？")) return;
  try {
    await api.deleteNotificationChannel(id);
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "删除失败";
  }
}

async function testChannel(id: number) {
  testingId.value = id;
  testResult.value = "";
  try {
    const res = await api.testNotificationChannel(id);
    testResult.value = res.success ? "发送成功" : "发送失败";
  } catch (err) {
    testResult.value = err instanceof Error ? err.message : "测试失败";
  } finally {
    setTimeout(() => { testingId.value = null; testResult.value = ""; }, 3000);
  }
}

function getConfigFields(type: string) {
  if (type === "email") {
    return [
      { key: "smtp_host", label: "SMTP服务器", placeholder: "smtp.example.com" },
      { key: "smtp_port", label: "端口", placeholder: "465" },
      { key: "username", label: "用户名", placeholder: "user@example.com" },
      { key: "password", label: "密码/授权码", placeholder: "******" },
      { key: "to", label: "收件人", placeholder: "admin@example.com" },
    ];
  }
  return [
    { key: "webhook_url", label: "Webhook URL", placeholder: "https://..." },
  ];
}

function formatTime(iso: string) {
  if (!iso) return "-";
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", { hour12: false });
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <div class="tab-bar">
        <button :class="['tab-btn', { active: activeTab === 'channels' }]" @click="switchTab('channels')">
          <Bell :size="15" />
          通知渠道
        </button>
        <button :class="['tab-btn', { active: activeTab === 'logs' }]" @click="switchTab('logs')">
          <FileText :size="15" />
          转发记录
        </button>
      </div>
      <div class="toolbar-right">
        <button v-if="activeTab === 'channels'" class="icon-button primary" type="button" @click="showCreate = !showCreate">
          <Plus :size="17" />
          <span>新增渠道</span>
        </button>
        <button class="icon-button" type="button" @click="activeTab === 'channels' ? load() : loadLogs()">
          <RefreshCw :size="17" />
          <span>刷新</span>
        </button>
      </div>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <!-- 通知渠道 Tab -->
    <template v-if="activeTab === 'channels'">
      <!-- 创建表单 -->
      <section v-if="showCreate" class="panel create-panel">
        <div class="panel-heading">
          <h2>新增通知渠道</h2>
        </div>
        <form class="form-grid" @submit.prevent="createChannel">
          <label class="form-field">
            <span>渠道名称</span>
            <input v-model="form.name" placeholder="如：运维告警群" required />
          </label>
          <label class="form-field">
            <span>渠道类型</span>
            <select v-model="form.channel_type">
              <option v-for="ct in channelTypes" :key="ct.value" :value="ct.value">{{ ct.label }}</option>
            </select>
          </label>
          <label v-for="field in getConfigFields(form.channel_type)" :key="field.key" class="form-field">
            <span>{{ field.label }}</span>
            <input
              v-model="form.config[field.key]"
              :placeholder="field.placeholder"
              :type="field.key === 'password' ? 'password' : 'text'"
            />
          </label>
          <div class="form-actions">
            <button type="submit" class="icon-button primary">创建</button>
            <button type="button" class="icon-button" @click="showCreate = false">取消</button>
          </div>
        </form>
      </section>

      <!-- 渠道列表 -->
      <section class="panel">
        <div class="panel-heading">
          <h2>通知渠道</h2>
          <span>{{ channels.length }} 个渠道</span>
        </div>
        <div v-if="loading" class="loading-row">加载中</div>
        <EmptyState v-else-if="!channels.length" title="暂无通知渠道" description="点击上方按钮新增" />
        <div v-else class="channel-grid">
          <div v-for="ch in channels" :key="ch.id" class="channel-card" :class="{ disabled: !ch.enabled }">
            <div class="channel-header">
              <div class="channel-icon" :style="{ background: getChannelInfo(ch.channel_type).color + '18', color: getChannelInfo(ch.channel_type).color }">
                <component :is="getChannelInfo(ch.channel_type).icon" :size="20" />
              </div>
              <div class="channel-meta">
                <strong>{{ ch.name }}</strong>
                <span class="channel-type">{{ getChannelInfo(ch.channel_type).label }}</span>
              </div>
              <div class="channel-status">
                <span :class="['dot', ch.enabled ? 'dot-on' : 'dot-off']"></span>
                {{ ch.enabled ? "启用" : "禁用" }}
              </div>
            </div>
            <div class="channel-actions">
              <button class="icon-button sm" type="button" :title="ch.enabled ? '禁用' : '启用'" @click="toggleChannel(ch)">
                <component :is="ch.enabled ? ToggleRight : ToggleLeft" :size="16" />
              </button>
              <button
                class="icon-button sm"
                type="button"
                title="发送测试"
                :disabled="testingId === ch.id"
                @click="testChannel(ch.id)"
              >
                <Send :size="16" />
              </button>
              <button class="icon-button sm danger" type="button" title="删除" @click="deleteChannel(ch.id)">
                <Trash2 :size="16" />
              </button>
              <span v-if="testingId === ch.id && testResult" class="test-result" :class="testResult === '发送成功' ? 'ok' : 'fail'">
                {{ testResult }}
              </span>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- 转发记录 Tab -->
    <template v-if="activeTab === 'logs'">
      <section class="panel">
        <div class="panel-heading">
          <h2>告警转发记录</h2>
          <div class="log-filters">
            <select v-model="logHours" @change="loadLogs">
              <option :value="6">最近 6 小时</option>
              <option :value="24">最近 24 小时</option>
              <option :value="72">最近 3 天</option>
              <option :value="168">最近 7 天</option>
            </select>
          </div>
        </div>
        <div v-if="loading" class="loading-row">加载中</div>
        <EmptyState v-else-if="!forwardingLogs.length" title="暂无转发记录" description="告警触发后会自动记录转发结果" />
        <table v-else class="data-table">
          <thead>
            <tr>
              <th>时间</th>
              <th>渠道</th>
              <th>类型</th>
              <th>状态</th>
              <th>错误信息</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in forwardingLogs" :key="log.id">
              <td class="time-cell">{{ formatTime(log.created_at) }}</td>
              <td>{{ log.channel_name }}</td>
              <td>
                <span class="channel-badge" :style="{ background: getChannelInfo(log.channel_type).color + '18', color: getChannelInfo(log.channel_type).color }">
                  {{ getChannelInfo(log.channel_type).label }}
                </span>
              </td>
              <td>
                <span :class="['status-tag', log.status === 'success' ? 'status-ok' : 'status-fail']">
                  <CheckCircle v-if="log.status === 'success'" :size="13" />
                  <XCircle v-else :size="13" />
                  {{ log.status === 'success' ? '成功' : '失败' }}
                </span>
              </td>
              <td class="error-cell">{{ log.error_message || '-' }}</td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </section>
</template>

<style scoped>
.tab-bar {
  display: flex;
  gap: 4px;
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 8px;
  padding: 3px;
}
.tab-btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font-size: 13px;
  color: var(--text, #374151);
  transition: all 0.15s;
}
.tab-btn:hover { background: var(--bg, #f3f4f6); }
.tab-btn.active { background: #3b82f6; color: #fff; }
.toolbar-right {
  display: flex;
  gap: 8px;
}
.channel-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 14px;
  padding: 16px;
}
.channel-card {
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 10px;
  padding: 16px;
  background: var(--surface, #fff);
  transition: box-shadow 0.2s;
}
.channel-card:hover {
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}
.channel-card.disabled {
  opacity: 0.55;
}
.channel-header {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;
}
.channel-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.channel-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.channel-meta strong {
  font-size: 14px;
}
.channel-type {
  font-size: 12px;
  opacity: 0.6;
}
.channel-status {
  font-size: 12px;
  display: flex;
  align-items: center;
  gap: 4px;
}
.dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
}
.dot-on { background: #22c55e; }
.dot-off { background: #94a3b8; }
.channel-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  border-top: 1px solid var(--border, #e5e7eb);
  padding-top: 10px;
}
.test-result {
  font-size: 12px;
  margin-left: auto;
}
.test-result.ok { color: #22c55e; }
.test-result.fail { color: #ef4444; }
.create-panel {
  border: 1px dashed var(--border, #d1d5db);
}
.form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 16px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-field span {
  font-size: 12px;
  font-weight: 600;
  opacity: 0.7;
}
.form-field input, .form-field select {
  padding: 8px 10px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg, #f9fafb);
}
.form-actions {
  grid-column: 1 / -1;
  display: flex;
  gap: 8px;
  justify-content: flex-end;
  padding-top: 8px;
}
.icon-button.primary {
  background: #3b82f6;
  color: #fff;
  border: none;
}
.icon-button.primary:hover {
  background: #2563eb;
}
.icon-button.danger {
  color: #ef4444;
}
.icon-button.sm {
  padding: 4px 6px;
}
.log-filters select {
  padding: 6px 10px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 6px;
  font-size: 12px;
  background: var(--bg, #f9fafb);
}
.data-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}
.data-table th {
  text-align: left;
  padding: 10px 12px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  opacity: 0.6;
  border-bottom: 1px solid var(--border, #e5e7eb);
}
.data-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border, #f3f4f6);
}
.time-cell {
  font-size: 12px;
  white-space: nowrap;
}
.error-cell {
  font-size: 12px;
  color: #ef4444;
  max-width: 200px;
  overflow: hidden;
  text-overflow: ellipsis;
}
.channel-badge {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
}
.status-tag {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 600;
}
.status-ok { color: #22c55e; }
.status-fail { color: #ef4444; }
</style>
