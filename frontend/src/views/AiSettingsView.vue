<script setup lang="ts">
import { Bot, Loader2, Save, CheckCircle } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { getApiBase, getToken } from "../api";

const loading = ref(true);
const saving = ref(false);
const saved = ref(false);

const globalEnabled = ref(false);
const globalReason = ref("");
const model = ref("");
const tenantEnabled = ref(true);
const ragEnabled = ref(true);

async function fetchConfig() {
  loading.value = true;
  try {
    const resp = await fetch(`${getApiBase()}/api/v1/aiops/config`, {
      headers: { Authorization: `Bearer ${getToken()}` },
    });
    if (resp.ok) {
      const data = await resp.json();
      globalEnabled.value = data.global_enabled;
      globalReason.value = data.global_reason;
      model.value = data.model;
      tenantEnabled.value = data.tenant_enabled;
      ragEnabled.value = data.rag_enabled;
    }
  } catch {
    // ignore
  }
  loading.value = false;
}

async function saveConfig() {
  saving.value = true;
  try {
    const resp = await fetch(`${getApiBase()}/api/v1/aiops/config`, {
      method: "PUT",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({
        enabled: tenantEnabled.value,
      }),
    });
    if (resp.ok) {
      saved.value = true;
      setTimeout(() => (saved.value = false), 2000);
    }
  } catch {
    // ignore
  }
  saving.value = false;
}

onMounted(fetchConfig);
</script>

<template>
  <div class="page">
    <div v-if="loading" class="loading">
      <Loader2 :size="24" class="spin" />
    </div>
    <template v-else>
      <div class="card">
        <h3>
          <Bot :size="20" />
          AI 运维助手配置
        </h3>

        <div class="status-section">
          <div class="status-row">
            <span>全局状态</span>
            <span :class="['status-badge', globalEnabled ? 'on' : 'off']">
              {{ globalEnabled ? "已启用" : "未启用" }}
            </span>
          </div>
          <div v-if="!globalEnabled && globalReason" class="hint">
            提示: 请在环境变量中设置 <code>AIOPS_ENABLED=true</code> 和 <code>AIOPS_API_KEY</code> 以启用全局 AI 功能
          </div>
          <div class="status-row">
            <span>当前模型</span>
            <span class="mono">{{ model || "未配置" }}</span>
          </div>
          <div class="status-row">
            <span>RAG 知识库</span>
            <span :class="['status-badge', ragEnabled ? 'on' : 'off']">
              {{ ragEnabled ? "已启用" : "未启用" }}
            </span>
          </div>
        </div>

        <div class="form-section">
          <label class="toggle-row">
            <input v-model="tenantEnabled" type="checkbox" />
            <span>启用当前租户的 AI 功能</span>
          </label>
          <p class="hint">关闭后，当前租户的用户将无法使用 AI 对话功能</p>
        </div>

        <div class="actions">
          <button class="btn primary" :disabled="saving" @click="saveConfig">
            <Save :size="16" />
            {{ saving ? "保存中..." : "保存配置" }}
          </button>
          <Transition name="fade">
            <span v-if="saved" class="saved-hint">
              <CheckCircle :size="16" /> 已保存
            </span>
          </Transition>
        </div>
      </div>
    </template>
  </div>
</template>

<style scoped>
.page {
  padding: 24px;
  max-width: 640px;
}
.loading {
  display: flex;
  justify-content: center;
  padding: 48px;
}
.card {
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 12px;
  padding: 24px;
}
.card h3 {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0 0 20px;
}
.status-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 24px;
}
.status-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.status-badge {
  padding: 2px 10px;
  border-radius: 999px;
  font-size: 0.85em;
}
.status-badge.on {
  background: #d1fae5;
  color: #065f46;
}
.status-badge.off {
  background: #fee2e2;
  color: #991b1b;
}
.mono {
  font-family: monospace;
  font-size: 0.9em;
}
.form-section {
  margin-bottom: 24px;
}
.toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.hint {
  font-size: 0.85em;
  color: var(--text-secondary, #6b7280);
  margin-top: 4px;
}
.hint code {
  background: var(--surface-secondary, #f3f4f6);
  padding: 1px 4px;
  border-radius: 3px;
  font-size: 0.9em;
}
.actions {
  display: flex;
  align-items: center;
  gap: 12px;
}
.btn {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 8px;
  border: none;
  cursor: pointer;
  font-size: 0.9em;
}
.btn.primary {
  background: var(--primary, #3b82f6);
  color: #fff;
}
.btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}
.saved-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #10b981;
  font-size: 0.85em;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.fade-enter-active,
.fade-leave-active {
  transition: opacity 0.3s;
}
.fade-enter-from,
.fade-leave-to {
  opacity: 0;
}
</style>
