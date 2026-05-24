<script setup lang="ts">
import {
  Save,
  RefreshCw,
  Server,
  Database,
  Shield,
  Cpu,
  User,
  Globe,
  FileText,
  AlertCircle,
  CheckCircle2,
  X,
  Eye,
  EyeOff,
  RotateCw
} from "lucide-vue-next";
import { onMounted, ref, computed } from "vue";
import { api } from "../api";
import type { PlatformConfig, PlatformConfigSchema } from "../types";

const config = ref<Record<string, any>>({});
const schema = ref<PlatformConfigSchema>({});
const configPath = ref("");
const modifiedAt = ref("");
const isProduction = ref(false);
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const success = ref("");
const needRestart = ref(false);
const restartFields = ref<string[]>([]);
const showPasswords = ref<Set<string>>(new Set());
const activeCategory = ref("");

const iconMap: Record<string, any> = {
  server: Server,
  database: Database,
  shield: Shield,
  cpu: Cpu,
  user: User,
  globe: Globe,
  "file-text": FileText,
};

const categories = computed(() => {
  const cats = Object.entries(schema.value).map(([key, def]) => ({
    key,
    label: def.label,
    icon: iconMap[def.icon] || Server,
    fields: def.fields,
  }));
  if (cats.length && !activeCategory.value) {
    activeCategory.value = cats[0].key;
  }
  return cats;
});

const activeCategoryDef = computed(() => {
  return categories.value.find(c => c.key === activeCategory.value);
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const res = await api.platformConfig();
    config.value = res.config;
    schema.value = res.schema;
    configPath.value = res.config_path;
    modifiedAt.value = res.modified_at || "";
    isProduction.value = res.is_production;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function save() {
  saving.value = true;
  error.value = "";
  success.value = "";
  try {
    const res = await api.savePlatformConfig(config.value);
    success.value = res.message;
    needRestart.value = res.need_restart;
    restartFields.value = res.restart_fields || [];
    setTimeout(() => { success.value = ""; }, 5000);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

function togglePassword(fieldKey: string) {
  if (showPasswords.value.has(fieldKey)) {
    showPasswords.value.delete(fieldKey);
  } else {
    showPasswords.value.add(fieldKey);
  }
}

function isSensitive(fieldKey: string) {
  return fieldKey.includes("password") || fieldKey.includes("secret") || fieldKey.includes("key");
}

function needsRestart(fieldKey: string) {
  return ["host", "port", "database_url", "redis_url", "workers", "jwt_algorithm"].includes(fieldKey);
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <!-- 顶部工具栏 -->
    <div class="config-toolbar">
      <div class="config-tabs">
        <button
          v-for="cat in categories"
          :key="cat.key"
          :class="['config-tab', { active: activeCategory === cat.key }]"
          @click="activeCategory = cat.key"
        >
          <component :is="cat.icon" :size="15" />
          {{ cat.label }}
        </button>
      </div>
      <div class="config-actions">
        <button class="icon-button" type="button" @click="load" title="重新加载">
          <RefreshCw :size="16" />
        </button>
        <button class="icon-button primary" type="button" :disabled="saving" @click="save">
          <Save :size="16" />
          <span>{{ saving ? "保存中..." : "保存配置" }}</span>
        </button>
      </div>
    </div>

    <!-- 提示 -->
    <div v-if="error" class="alert-line">
      <AlertCircle :size="16" />
      {{ error }}
      <button class="alert-close" @click="error = ''"><X :size="14" /></button>
    </div>
    <div v-if="success" class="success-line">
      <CheckCircle2 :size="16" />
      {{ success }}
    </div>
    <div v-if="needRestart" class="restart-line">
      <RotateCw :size="16" />
      以下配置需要重启服务才能生效: {{ restartFields.join(', ') }}
    </div>

    <!-- 生产环境警告 -->
    <div v-if="isProduction" class="warn-line">
      <AlertCircle :size="16" />
      当前为生产环境，修改配置需谨慎
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading-row">加载配置中...</div>

    <!-- 配置表单 -->
    <template v-else-if="activeCategoryDef">
      <section class="panel">
        <div class="panel-heading">
          <h2>
            <component :is="activeCategoryDef.icon" :size="18" style="vertical-align: -3px; margin-right: 6px;" />
            {{ activeCategoryDef.label }}
          </h2>
        </div>
        <div class="config-form">
          <div v-for="(fieldDef, fieldKey) in activeCategoryDef.fields" :key="fieldKey" class="config-field">
            <div class="config-field-header">
              <label :for="'cfg-' + fieldKey">{{ fieldDef.label }}</label>
              <span v-if="needsRestart(fieldKey)" class="restart-badge">需重启</span>
            </div>

            <!-- 文本 / 密码 -->
            <template v-if="fieldDef.type === 'text' || fieldDef.type === 'password'">
              <div class="input-wrap">
                <input
                  :id="'cfg-' + fieldKey"
                  v-model="config[fieldKey]"
                  :type="fieldDef.type === 'password' && !showPasswords.has(fieldKey) ? 'password' : 'text'"
                  :placeholder="fieldDef.default"
                />
                <button
                  v-if="fieldDef.type === 'password' || isSensitive(fieldKey)"
                  class="eye-btn"
                  type="button"
                  @click="togglePassword(fieldKey)"
                >
                  <Eye v-if="showPasswords.has(fieldKey)" :size="16" />
                  <EyeOff v-else :size="16" />
                </button>
              </div>
            </template>

            <!-- 数字 -->
            <template v-else-if="fieldDef.type === 'number'">
              <input
                :id="'cfg-' + fieldKey"
                v-model.number="config[fieldKey]"
                type="number"
                :min="fieldDef.min"
                :max="fieldDef.max"
                :placeholder="String(fieldDef.default)"
              />
            </template>

            <!-- 下拉 -->
            <template v-else-if="fieldDef.type === 'select'">
              <select :id="'cfg-' + fieldKey" v-model="config[fieldKey]">
                <option v-for="opt in fieldDef.options" :key="opt" :value="opt">{{ opt }}</option>
              </select>
            </template>

            <p v-if="fieldDef.hint" class="field-hint">{{ fieldDef.hint }}</p>
          </div>
        </div>
      </section>
    </template>

    <!-- 底部状态 -->
    <div class="config-status">
      <span>配置文件: {{ configPath }}</span>
      <span v-if="modifiedAt">最后修改: {{ new Date(modifiedAt).toLocaleString() }}</span>
    </div>
  </section>
</template>

<style scoped>
.config-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}
.config-tabs {
  display: flex;
  gap: 2px;
  background: var(--surface, #fff);
  border: 1px solid var(--line, #e2e8f0);
  border-radius: 8px;
  padding: 4px;
  flex-wrap: wrap;
}
.config-tab {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 14px;
  border: none;
  border-radius: 6px;
  background: transparent;
  color: var(--muted, #667485);
  font-size: 13px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
  white-space: nowrap;
}
.config-tab:hover {
  background: var(--surface-2, #f8fafc);
}
.config-tab.active {
  background: #e7eefc;
  color: #155eef;
}
.config-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}
.icon-button.primary {
  background: #3b82f6;
  color: #fff;
  border: none;
}
.icon-button.primary:hover {
  background: #2563eb;
}

/* 配置表单 */
.config-form {
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}
.config-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.config-field-header {
  display: flex;
  align-items: center;
  gap: 8px;
}
.config-field-header label {
  font-size: 14px;
  font-weight: 600;
  color: var(--text, #16202a);
}
.restart-badge {
  display: inline-block;
  padding: 1px 6px;
  border-radius: 4px;
  background: #fef3c7;
  color: #92400e;
  font-size: 10px;
  font-weight: 700;
}
.config-field input,
.config-field select {
  width: 100%;
  max-width: 520px;
  padding: 10px 14px;
  border: 1px solid var(--line, #d1d5db);
  border-radius: 8px;
  font-size: 14px;
  background: var(--surface, #fff);
  color: var(--text, #16202a);
  transition: border-color 0.15s, box-shadow 0.15s;
}
.config-field input:focus,
.config-field select:focus {
  outline: none;
  border-color: #3b82f6;
  box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.1);
}
.config-field input::placeholder {
  color: #94a3b8;
}
.input-wrap {
  position: relative;
  max-width: 520px;
}
.input-wrap input {
  padding-right: 40px;
}
.eye-btn {
  position: absolute;
  right: 8px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--muted, #94a3b8);
  cursor: pointer;
  padding: 4px;
}
.field-hint {
  margin: 0;
  font-size: 12px;
  color: var(--muted, #94a3b8);
  max-width: 520px;
}

/* 提示 */
.success-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #f0fdf4;
  border: 1px solid #bbf7d0;
  color: #15803d;
  font-size: 13px;
}
.restart-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fffbeb;
  border: 1px solid #fde68a;
  color: #92400e;
  font-size: 13px;
}
.warn-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  color: #991b1b;
  font-size: 13px;
}
.alert-close {
  margin-left: auto;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
  padding: 2px;
}

/* 状态栏 */
.config-status {
  display: flex;
  gap: 16px;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--surface, #fff);
  border: 1px solid var(--line, #e2e8f0);
  font-size: 12px;
  color: var(--muted, #667485);
}
</style>
