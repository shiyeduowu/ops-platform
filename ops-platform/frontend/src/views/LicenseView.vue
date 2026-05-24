<script setup lang="ts">
import { Copy, RefreshCw, Save, ShieldCheck } from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { api } from "../api";
import EmptyState from "../components/EmptyState.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { LicenseOverview } from "../types";

const overview = ref<LicenseOverview | null>(null);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const form = ref({
  plan: "enterprise",
  max_agents: 100,
  status: "active",
  expire_at: ""
});

function syncForm() {
  const license = overview.value?.license;
  if (!license) return;
  form.value = {
    plan: license.plan,
    max_agents: license.max_agents,
    status: license.status,
    expire_at: license.expire_at ? license.expire_at.slice(0, 16) : ""
  };
}

async function load() {
  loading.value = true;
  error.value = "";
  try {
    overview.value = await api.license();
    syncForm();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    await api.updateLicense({
      plan: form.value.plan,
      max_agents: Number(form.value.max_agents),
      status: form.value.status,
      expire_at: form.value.expire_at ? new Date(form.value.expire_at).toISOString() : null
    });
    message.value = "已保存";
    await load();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

async function copyCode(code: string) {
  await navigator.clipboard.writeText(code);
  message.value = "激活码已复制";
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <button class="icon-button" type="button" title="刷新授权" @click="load">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </div>
    <div v-if="error" class="alert-line">{{ error }}</div>

    <div class="two-column license-grid">
      <section class="panel">
        <div class="panel-heading">
          <h2>租户授权</h2>
          <ShieldCheck :size="20" />
        </div>
        <div class="form-grid">
          <label>
            <span>租户</span>
            <input :value="overview?.tenant.name || '-'" disabled />
          </label>
          <label>
            <span>套餐</span>
            <select v-model="form.plan">
              <option value="free">free</option>
              <option value="standard">standard</option>
              <option value="enterprise">enterprise</option>
            </select>
          </label>
          <label>
            <span>最大 Agent 数</span>
            <input v-model.number="form.max_agents" type="number" min="0" />
          </label>
          <label>
            <span>状态</span>
            <select v-model="form.status">
              <option value="active">active</option>
              <option value="paused">paused</option>
              <option value="expired">expired</option>
            </select>
          </label>
          <label>
            <span>到期时间</span>
            <input v-model="form.expire_at" type="datetime-local" />
          </label>
        </div>
        <div class="form-actions">
          <span class="success-text">{{ message }}</span>
          <button class="primary-button fit" type="button" :disabled="saving" @click="save">
            <Save :size="17" />
            <span>{{ saving ? "保存中" : "保存" }}</span>
          </button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-heading">
          <h2>激活码</h2>
          <span>{{ overview?.activation_codes.length || 0 }}</span>
        </div>
        <EmptyState v-if="!overview?.activation_codes.length && !loading" title="暂无激活码" />
        <div v-else class="code-list">
          <article v-for="code in overview?.activation_codes" :key="code.id" class="code-item">
            <div>
              <code>{{ code.code }}</code>
              <span>{{ code.used_count }} / {{ code.max_uses }}</span>
            </div>
            <StatusBadge :value="code.status" />
            <button class="icon-only" type="button" title="复制激活码" @click="copyCode(code.code)">
              <Copy :size="16" />
            </button>
          </article>
        </div>
      </section>
    </div>
  </section>
</template>
