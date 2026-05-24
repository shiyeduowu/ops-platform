<script setup lang="ts">
import {
  RefreshCw,
  Save,
  Plus,
  X,
  Settings2,
  Code,
  Server,
  FileText,
  Gauge,
  Clock,
  Tag,
  BookOpen,
  FolderSearch,
  Trash2,
  Cog
} from "lucide-vue-next";
import { computed, onMounted, ref, watch } from "vue";
import { api } from "../api";
import EmptyState from "../components/EmptyState.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent, AgentConfig, AgentConfigSchema } from "../types";

const agents = ref<Agent[]>([]);
const selectedAgentId = ref("");
const config = ref<AgentConfig | null>(null);
const schema = ref<AgentConfigSchema>({});
const loading = ref(false);
const saving = ref(false);
const error = ref("");
const message = ref("");
const advancedMode = ref(false);
const jsonText = ref("");
const jsonError = ref("");

// 表单数据
const portChecks = ref<number[]>([]);
const logSources = ref<Array<{ path: string; service_key: string; encoding: string; max_lines_per_tick: number }>>([]);
const logKeywords = ref<string[]>([]);
const keywordInput = ref("");
const diskThreshold = ref(10);
const cpuThreshold = ref(90);
const memoryThreshold = ref(90);
const checkInterval = ref(30);
const heartbeatInterval = ref(7200);

// 新增：服务目录
const serviceCatalog = ref<Array<{ service_key: string; name: string; product_line: string; owner: string; description: string }>>([]);
// 新增：Windows 服务
const windowsServices = ref<string[]>([]);
const winSvcInput = ref("");
// 新增：日志自动发现
const logDiscovery = ref<Array<{ root: string; glob: string; service_key: string; id_prefix: string; scan_interval_seconds: number }>>([]);
// 新增：高级设置
const stackDateLineRegex = ref("^\\d{4}-\\d{2}-\\d{2}");
const maxConcurrentTails = ref(48);
// 新增：日志清理
const logCleanupEnabled = ref(false);
const logCleanupRetentionDays = ref(30);
const logCleanupDryRun = ref(true);
const logCleanupIntervalSeconds = ref(3600);

const selectedAgent = computed(() => agents.value.find((a) => a.agent_id === selectedAgentId.value));

function syncFromConfig() {
  if (!config.value) return;
  const cj = config.value.config_json;
  portChecks.value = Array.isArray(cj.port_checks) ? [...cj.port_checks] : [];
  logSources.value = Array.isArray(cj.log_sources) ? cj.log_sources.map((s: any) => ({
    path: s.path || "",
    service_key: s.service_key || "",
    encoding: s.encoding || "utf-8",
    max_lines_per_tick: Number(s.max_lines_per_tick) || 200,
  })) : [];
  logKeywords.value = Array.isArray(cj.log_keywords) ? [...cj.log_keywords] : [];
  diskThreshold.value = Number(cj.disk_threshold) ?? 10;
  cpuThreshold.value = Number(cj.cpu_threshold) ?? 90;
  memoryThreshold.value = Number(cj.memory_threshold) ?? 90;
  checkInterval.value = Number(cj.check_interval_seconds) ?? 30;
  heartbeatInterval.value = Number(cj.heartbeat_interval_seconds) ?? 7200;

  // 新增字段
  serviceCatalog.value = Array.isArray(cj.service_catalog) ? cj.service_catalog.map((s: any) => ({
    service_key: s.service_key || "",
    name: s.name || "",
    product_line: s.product_line || "",
    owner: s.owner || "",
    description: s.description || "",
  })) : [];
  windowsServices.value = Array.isArray(cj.windows_services) ? [...cj.windows_services] : [];
  logDiscovery.value = Array.isArray(cj.log_discovery) ? cj.log_discovery.map((d: any) => ({
    root: d.root || "",
    glob: d.glob || "*.log",
    service_key: d.service_key || "{folder}",
    id_prefix: d.id_prefix || "",
    scan_interval_seconds: Number(d.scan_interval_seconds) || 45,
  })) : [];
  stackDateLineRegex.value = String(cj.stack_date_line_regex || "^\\d{4}-\\d{2}-\\d{2}");
  maxConcurrentTails.value = Number(cj.max_concurrent_tails) ?? 48;
  logCleanupEnabled.value = Boolean(cj.log_cleanup_enabled);
  logCleanupRetentionDays.value = Number(cj.log_cleanup_retention_days) ?? 30;
  logCleanupDryRun.value = cj.log_cleanup_dry_run !== false;
  logCleanupIntervalSeconds.value = Number(cj.log_cleanup_interval_seconds) ?? 3600;

  jsonText.value = JSON.stringify(cj, null, 2);
  jsonError.value = "";
}

function buildConfigJson(): Record<string, unknown> {
  return {
    port_checks: portChecks.value.filter((p) => p > 0),
    log_sources: logSources.value.filter((s) => s.path.trim()),
    log_keywords: logKeywords.value,
    disk_threshold: diskThreshold.value,
    cpu_threshold: cpuThreshold.value,
    memory_threshold: memoryThreshold.value,
    check_interval_seconds: checkInterval.value,
    heartbeat_interval_seconds: heartbeatInterval.value,
    service_catalog: serviceCatalog.value.filter((s) => s.service_key.trim()),
    windows_services: windowsServices.value,
    log_discovery: logDiscovery.value.filter((d) => d.root.trim()),
    stack_date_line_regex: stackDateLineRegex.value,
    max_concurrent_tails: maxConcurrentTails.value,
    log_cleanup_enabled: logCleanupEnabled.value,
    log_cleanup_retention_days: logCleanupRetentionDays.value,
    log_cleanup_dry_run: logCleanupDryRun.value,
    log_cleanup_interval_seconds: logCleanupIntervalSeconds.value,
  };
}

function validateJson(): boolean {
  try {
    JSON.parse(jsonText.value);
    jsonError.value = "";
    return true;
  } catch (err) {
    jsonError.value = `JSON 格式错误：${err instanceof Error ? err.message : "未知错误"}`;
    return false;
  }
}

async function loadAgents() {
  loading.value = true;
  error.value = "";
  try {
    const agentsRes = await api.agents(); agents.value = agentsRes.items ?? agentsRes;
    if (!selectedAgentId.value && agents.value.length) {
      selectedAgentId.value = agents.value[0].agent_id;
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function loadConfigAndSchema() {
  if (!selectedAgentId.value) return;
  loading.value = true;
  error.value = "";
  try {
    const [configData, schemaData] = await Promise.all([
      api.config(selectedAgentId.value),
      api.agentConfigSchema(),
    ]);
    config.value = configData;
    schema.value = schemaData.schema;
    syncFromConfig();
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  if (!selectedAgentId.value) return;
  saving.value = true;
  message.value = "";
  error.value = "";
  try {
    let configJson: Record<string, unknown>;
    if (advancedMode.value) {
      if (!validateJson()) {
        saving.value = false;
        return;
      }
      configJson = JSON.parse(jsonText.value);
    } else {
      configJson = buildConfigJson();
    }
    config.value = await api.updateConfig(selectedAgentId.value, configJson);
    syncFromConfig();
    message.value = `已保存，版本: ${config.value.config_version}`;
    setTimeout(() => { message.value = ""; }, 5000);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "保存失败";
  } finally {
    saving.value = false;
  }
}

// 端口列表操作
function addPort() {
  portChecks.value.push(0);
}
function removePort(index: number) {
  portChecks.value.splice(index, 1);
}

// 日志源操作
function addLogSource() {
  logSources.value.push({ path: "", service_key: "", encoding: "utf-8", max_lines_per_tick: 200 });
}
function removeLogSource(index: number) {
  logSources.value.splice(index, 1);
}

// 关键词操作
function addKeyword() {
  const kw = keywordInput.value.trim();
  if (kw && !logKeywords.value.includes(kw)) {
    logKeywords.value.push(kw);
  }
  keywordInput.value = "";
}
function removeKeyword(index: number) {
  logKeywords.value.splice(index, 1);
}
function onKeywordKeydown(e: KeyboardEvent) {
  if (e.key === "Enter") {
    e.preventDefault();
    addKeyword();
  }
}

// 服务目录操作
function addServiceCatalogItem() {
  serviceCatalog.value.push({ service_key: "", name: "", product_line: "", owner: "", description: "" });
}
function removeServiceCatalogItem(index: number) {
  serviceCatalog.value.splice(index, 1);
}

// Windows 服务操作
function addWindowsService() {
  const name = winSvcInput.value.trim();
  if (name && !windowsServices.value.includes(name)) {
    windowsServices.value.push(name);
  }
  winSvcInput.value = "";
}
function removeWindowsService(index: number) {
  windowsServices.value.splice(index, 1);
}
function onWinSvcKeydown(e: KeyboardEvent) {
  if (e.key === "Enter") {
    e.preventDefault();
    addWindowsService();
  }
}

// 日志发现操作
function addLogDiscovery() {
  logDiscovery.value.push({ root: "", glob: "*.log", service_key: "{folder}", id_prefix: "", scan_interval_seconds: 45 });
}
function removeLogDiscovery(index: number) {
  logDiscovery.value.splice(index, 1);
}

function toggleAdvanced() {
  if (!advancedMode.value) {
    jsonText.value = JSON.stringify(buildConfigJson(), null, 2);
    jsonError.value = "";
  } else {
    if (!validateJson()) return;
    try {
      const parsed = JSON.parse(jsonText.value);
      portChecks.value = Array.isArray(parsed.port_checks) ? [...parsed.port_checks] : [];
      logSources.value = Array.isArray(parsed.log_sources) ? parsed.log_sources.map((s: any) => ({
        path: s.path || "", service_key: s.service_key || "",
        encoding: s.encoding || "utf-8", max_lines_per_tick: Number(s.max_lines_per_tick) || 200,
      })) : [];
      logKeywords.value = Array.isArray(parsed.log_keywords) ? [...parsed.log_keywords] : [];
      diskThreshold.value = Number(parsed.disk_threshold) ?? 10;
      cpuThreshold.value = Number(parsed.cpu_threshold) ?? 90;
      memoryThreshold.value = Number(parsed.memory_threshold) ?? 90;
      checkInterval.value = Number(parsed.check_interval_seconds) ?? 30;
      heartbeatInterval.value = Number(parsed.heartbeat_interval_seconds) ?? 7200;
      serviceCatalog.value = Array.isArray(parsed.service_catalog) ? parsed.service_catalog.map((s: any) => ({
        service_key: s.service_key || "", name: s.name || "",
        product_line: s.product_line || "", owner: s.owner || "", description: s.description || "",
      })) : [];
      windowsServices.value = Array.isArray(parsed.windows_services) ? [...parsed.windows_services] : [];
      logDiscovery.value = Array.isArray(parsed.log_discovery) ? parsed.log_discovery.map((d: any) => ({
        root: d.root || "", glob: d.glob || "*.log", service_key: d.service_key || "{folder}",
        id_prefix: d.id_prefix || "", scan_interval_seconds: Number(d.scan_interval_seconds) || 45,
      })) : [];
      stackDateLineRegex.value = parsed.stack_date_line_regex || "^\\d{4}-\\d{2}-\\d{2}";
      maxConcurrentTails.value = Number(parsed.max_concurrent_tails) ?? 48;
      logCleanupEnabled.value = Boolean(parsed.log_cleanup_enabled);
      logCleanupRetentionDays.value = Number(parsed.log_cleanup_retention_days) ?? 30;
      logCleanupDryRun.value = parsed.log_cleanup_dry_run !== false;
      logCleanupIntervalSeconds.value = Number(parsed.log_cleanup_interval_seconds) ?? 3600;
    } catch { /* keep current values */ }
  }
  advancedMode.value = !advancedMode.value;
}

watch(selectedAgentId, (val) => { if (val) loadConfigAndSchema(); });
onMounted(loadAgents);
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <label class="select-box grow">
        <select v-model="selectedAgentId">
          <option value="">选择 Agent</option>
          <option v-for="agent in agents" :key="agent.agent_id" :value="agent.agent_id">
            {{ agent.hostname }} ({{ agent.ip || '-' }}) / {{ agent.agent_id.slice(0, 12) }}...
          </option>
        </select>
      </label>
      <button class="icon-button" type="button" @click="loadConfigAndSchema">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
      <button :class="['icon-button', { active: advancedMode }]" type="button" @click="toggleAdvanced">
        <Code :size="17" />
        <span>{{ advancedMode ? "表单模式" : "高级模式" }}</span>
      </button>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <section v-if="selectedAgent" class="detail-hero compact-hero">
      <div>
        <p class="eyebrow">{{ selectedAgent.agent_id }}</p>
        <h2>{{ selectedAgent.hostname }}</h2>
      </div>
      <div class="hero-right">
        <StatusBadge :value="selectedAgent.status" />
        <span class="version-tag">配置版本: {{ config?.config_version || "-" }}</span>
      </div>
    </section>

    <EmptyState v-if="!agents.length && !loading" title="暂无已注册 Agent" />

    <!-- 高级模式：JSON 编辑 -->
    <template v-if="advancedMode && selectedAgent">
      <section class="panel">
        <div class="panel-heading">
          <h2>JSON 编辑</h2>
          <span class="hint">直接编辑 config_json 原始数据</span>
        </div>
        <textarea
          v-model="jsonText"
          :class="['code-editor', 'tall', { 'has-error': jsonError }]"
          spellcheck="false"
          @input="validateJson"
          @blur="validateJson"
        ></textarea>
        <div v-if="jsonError" class="json-error">{{ jsonError }}</div>
      </section>
    </template>

    <!-- 表单模式 -->
    <template v-if="!advancedMode && selectedAgent">
      <!-- 端口检测 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Server :size="16" style="vertical-align:-2px;margin-right:6px" />端口检测</h2>
          <span class="hint">{{ schema.port_checks?.hint || "Agent 本地检测的 TCP 端口" }}</span>
        </div>
        <div class="dynamic-list">
          <div v-for="(port, idx) in portChecks" :key="idx" class="dynamic-row">
            <input
              v-model.number="portChecks[idx]"
              type="number"
              min="1"
              max="65535"
              placeholder="端口号 (如 8080)"
              class="port-input"
            />
            <button class="icon-button sm danger" type="button" @click="removePort(idx)">
              <X :size="14" />
            </button>
          </div>
          <button class="icon-button sm" type="button" @click="addPort">
            <Plus :size="14" />
            <span>添加端口</span>
          </button>
        </div>
      </section>

      <!-- 日志采集 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><FileText :size="16" style="vertical-align:-2px;margin-right:6px" />日志采集源</h2>
          <span class="hint">{{ schema.log_sources?.hint || "配置日志文件路径" }}</span>
        </div>
        <div class="dynamic-list">
          <div v-for="(src, idx) in logSources" :key="idx" class="log-source-row">
            <div class="log-source-fields">
              <input v-model="src.path" placeholder="日志路径 (如 C:\logs\app\error.log)" class="flex-input" />
              <input v-model="src.service_key" placeholder="服务标识" class="small-input" />
              <input v-model="src.encoding" placeholder="编码" class="tiny-input" />
              <input v-model.number="src.max_lines_per_tick" type="number" min="1" max="10000" placeholder="最大行数" class="tiny-input" />
            </div>
            <button class="icon-button sm danger" type="button" @click="removeLogSource(idx)">
              <X :size="14" />
            </button>
          </div>
          <button class="icon-button sm" type="button" @click="addLogSource">
            <Plus :size="14" />
            <span>添加日志源</span>
          </button>
        </div>
      </section>

      <!-- 日志关键词 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Tag :size="16" style="vertical-align:-2px;margin-right:6px" />日志告警关键词</h2>
          <span class="hint">{{ schema.log_keywords?.hint || "匹配关键词触发告警" }}</span>
        </div>
        <div class="tags-area">
          <span v-for="(kw, idx) in logKeywords" :key="idx" class="tag-item">
            {{ kw }}
            <button class="tag-remove" type="button" @click="removeKeyword(idx)">&times;</button>
          </span>
          <input
            v-model="keywordInput"
            placeholder="输入关键词，回车添加"
            class="tag-input"
            @keydown="onKeywordKeydown"
          />
        </div>
      </section>

      <!-- 告警阈值 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Gauge :size="16" style="vertical-align:-2px;margin-right:6px" />告警阈值</h2>
        </div>
        <div class="threshold-grid">
          <label class="form-field">
            <span>{{ schema.disk_threshold?.label || "磁盘剩余空间阈值" }}</span>
            <div class="input-with-unit">
              <input v-model.number="diskThreshold" type="number" :min="schema.disk_threshold?.min || 1" :max="schema.disk_threshold?.max || 99" />
              <span class="unit">%</span>
            </div>
            <small v-if="schema.disk_threshold?.hint">{{ schema.disk_threshold.hint }}</small>
          </label>
          <label class="form-field">
            <span>{{ schema.cpu_threshold?.label || "CPU 使用率阈值" }}</span>
            <div class="input-with-unit">
              <input v-model.number="cpuThreshold" type="number" :min="schema.cpu_threshold?.min || 1" :max="schema.cpu_threshold?.max || 100" />
              <span class="unit">%</span>
            </div>
            <small v-if="schema.cpu_threshold?.hint">{{ schema.cpu_threshold.hint }}</small>
          </label>
          <label class="form-field">
            <span>{{ schema.memory_threshold?.label || "内存使用率阈值" }}</span>
            <div class="input-with-unit">
              <input v-model.number="memoryThreshold" type="number" :min="schema.memory_threshold?.min || 1" :max="schema.memory_threshold?.max || 100" />
              <span class="unit">%</span>
            </div>
            <small v-if="schema.memory_threshold?.hint">{{ schema.memory_threshold.hint }}</small>
          </label>
        </div>
      </section>

      <!-- 检测频率 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Clock :size="16" style="vertical-align:-2px;margin-right:6px" />检测频率</h2>
        </div>
        <div class="threshold-grid">
          <label class="form-field">
            <span>{{ schema.check_interval_seconds?.label || "本地检测间隔" }}</span>
            <div class="input-with-unit">
              <input v-model.number="checkInterval" type="number" :min="schema.check_interval_seconds?.min || 10" :max="schema.check_interval_seconds?.max || 3600" />
              <span class="unit">秒</span>
            </div>
            <small v-if="schema.check_interval_seconds?.hint">{{ schema.check_interval_seconds.hint }}</small>
          </label>
          <label class="form-field">
            <span>{{ schema.heartbeat_interval_seconds?.label || "心跳间隔" }}</span>
            <div class="input-with-unit">
              <input v-model.number="heartbeatInterval" type="number" :min="schema.heartbeat_interval_seconds?.min || 60" :max="schema.heartbeat_interval_seconds?.max || 86400" />
              <span class="unit">秒</span>
            </div>
            <small v-if="schema.heartbeat_interval_seconds?.hint">{{ schema.heartbeat_interval_seconds.hint }}</small>
          </label>
        </div>
      </section>
    </template>

    <!-- 服务目录 -->
    <template v-if="!advancedMode && selectedAgent">
      <section class="panel">
        <div class="panel-heading">
          <h2><BookOpen :size="16" style="vertical-align:-2px;margin-right:6px" />服务目录</h2>
          <span class="hint">定义服务元数据，关联端口、进程、日志的统一 service_key</span>
        </div>
        <div class="dynamic-list">
          <div v-for="(svc, idx) in serviceCatalog" :key="idx" class="catalog-row">
            <div class="catalog-fields">
              <input v-model="svc.service_key" placeholder="服务标识 (service_key)" class="small-input" />
              <input v-model="svc.name" placeholder="服务名称" class="small-input" />
              <input v-model="svc.product_line" placeholder="产品线" class="small-input" />
              <input v-model="svc.owner" placeholder="负责人" class="small-input" />
              <input v-model="svc.description" placeholder="描述" class="flex-input" />
            </div>
            <button class="icon-button sm danger" type="button" @click="removeServiceCatalogItem(idx)">
              <X :size="14" />
            </button>
          </div>
          <button class="icon-button sm" type="button" @click="addServiceCatalogItem">
            <Plus :size="14" />
            <span>添加服务</span>
          </button>
        </div>
      </section>

      <!-- Windows 服务监控 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Server :size="16" style="vertical-align:-2px;margin-right:6px" />Windows 服务监控</h2>
          <span class="hint">需要监控的 Windows 服务名，Agent 会检测是否 RUNNING</span>
        </div>
        <div class="tags-area">
          <span v-for="(svc, idx) in windowsServices" :key="idx" class="tag-item">
            {{ svc }}
            <button class="tag-remove" type="button" @click="removeWindowsService(idx)">&times;</button>
          </span>
          <input
            v-model="winSvcInput"
            placeholder="输入服务名，回车添加"
            class="tag-input"
            @keydown="onWinSvcKeydown"
          />
        </div>
      </section>

      <!-- 日志自动发现 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><FolderSearch :size="16" style="vertical-align:-2px;margin-right:6px" />日志自动发现</h2>
          <span class="hint">自动扫描目录下的 */logs/ 子目录并 tail 新日志文件</span>
        </div>
        <div class="dynamic-list">
          <div v-for="(disc, idx) in logDiscovery" :key="idx" class="discovery-row">
            <div class="discovery-fields">
              <input v-model="disc.root" placeholder="扫描根目录 (如 C:\apps)" class="flex-input" />
              <input v-model="disc.glob" placeholder="*.log" class="tiny-input" />
              <input v-model="disc.service_key" placeholder="服务标识模板" class="small-input" />
              <input v-model="disc.id_prefix" placeholder="ID 前缀" class="tiny-input" />
              <input v-model.number="disc.scan_interval_seconds" type="number" min="5" max="3600" placeholder="扫描间隔" class="tiny-input" />
            </div>
            <button class="icon-button sm danger" type="button" @click="removeLogDiscovery(idx)">
              <X :size="14" />
            </button>
          </div>
          <button class="icon-button sm" type="button" @click="addLogDiscovery">
            <Plus :size="14" />
            <span>添加发现规则</span>
          </button>
        </div>
      </section>

      <!-- 高级设置 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Cog :size="16" style="vertical-align:-2px;margin-right:6px" />高级设置</h2>
        </div>
        <div class="threshold-grid">
          <label class="form-field">
            <span>堆栈日期行正则</span>
            <input v-model="stackDateLineRegex" placeholder="^\d{4}-\d{2}-\d{2}" />
            <small>用于识别日志新记录起始行，多行堆栈聚合后匹配关键词</small>
          </label>
          <label class="form-field">
            <span>最大并发 tail 数</span>
            <div class="input-with-unit">
              <input v-model.number="maxConcurrentTails" type="number" :min="1" :max="200" />
              <span class="unit">个</span>
            </div>
            <small>同时 tail 的日志文件数量上限</small>
          </label>
        </div>
      </section>

      <!-- 日志清理 -->
      <section class="panel">
        <div class="panel-heading">
          <h2><Trash2 :size="16" style="vertical-align:-2px;margin-right:6px" />日志清理</h2>
          <span class="hint">自动删除过期的日志文件</span>
        </div>
        <div class="cleanup-config">
          <label class="toggle-row">
            <input v-model="logCleanupEnabled" type="checkbox" />
            <span>启用日志清理</span>
          </label>
          <div v-if="logCleanupEnabled" class="threshold-grid">
            <label class="form-field">
              <span>保留天数</span>
              <div class="input-with-unit">
                <input v-model.number="logCleanupRetentionDays" type="number" :min="1" :max="365" />
                <span class="unit">天</span>
              </div>
            </label>
            <label class="form-field">
              <span>清理间隔</span>
              <div class="input-with-unit">
                <input v-model.number="logCleanupIntervalSeconds" type="number" :min="60" :max="86400" />
                <span class="unit">秒</span>
              </div>
            </label>
            <label class="toggle-row">
              <input v-model="logCleanupDryRun" type="checkbox" />
              <span>试运行模式（仅打印，不删除）</span>
            </label>
          </div>
        </div>
      </section>
    </template>

    <!-- 保存栏 -->
    <div v-if="selectedAgent" class="save-bar">
      <span v-if="message" class="success-text">{{ message }}</span>
      <button class="primary-button fit" type="button" :disabled="saving || !selectedAgentId" @click="saveConfig">
        <Save :size="17" />
        <span>{{ saving ? "保存中..." : "保存配置" }}</span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.hero-right {
  display: flex;
  align-items: center;
  gap: 12px;
}
.version-tag {
  font-size: 12px;
  padding: 3px 10px;
  background: var(--surface, #fff);
  border: 1px solid var(--line, #e5e7eb);
  border-radius: 6px;
  color: var(--muted, #6b7280);
}
.icon-button.active {
  background: #3b82f6;
  color: #fff;
  border-color: #3b82f6;
}
.hint {
  font-size: 12px;
  color: var(--muted, #9ca3af);
}

/* 动态列表 */
.dynamic-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 16px;
}
.dynamic-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.port-input {
  width: 200px;
}

/* 日志源 */
.log-source-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.log-source-fields {
  display: flex;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}
.flex-input {
  flex: 1;
  min-width: 200px;
}
.small-input {
  width: 140px;
}
.tiny-input {
  width: 100px;
}

/* 标签输入 */
.tags-area {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding: 16px;
  align-items: center;
}
.tag-item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  background: #3b82f6;
  color: #fff;
  border-radius: 6px;
  font-size: 13px;
  font-weight: 500;
}
.tag-remove {
  background: none;
  border: none;
  color: #fff;
  cursor: pointer;
  font-size: 16px;
  line-height: 1;
  padding: 0 2px;
  opacity: 0.7;
}
.tag-remove:hover {
  opacity: 1;
}
.tag-input {
  border: none;
  outline: none;
  font-size: 13px;
  padding: 4px 0;
  min-width: 150px;
  background: transparent;
}

/* 阈值网格 */
.threshold-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(260px, 1fr));
  gap: 16px;
  padding: 16px;
}
.form-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.form-field > span {
  font-size: 13px;
  font-weight: 600;
  color: var(--text, #374151);
}
.form-field small {
  font-size: 11px;
  color: var(--muted, #9ca3af);
}
.input-with-unit {
  display: flex;
  align-items: center;
  gap: 0;
}
.input-with-unit input {
  width: 120px;
  border-radius: 6px 0 0 6px;
}
.unit {
  padding: 8px 10px;
  background: var(--bg, #f3f4f6);
  border: 1px solid var(--line, #d1d5db);
  border-left: none;
  border-radius: 0 6px 6px 0;
  font-size: 12px;
  color: var(--muted, #6b7280);
}

/* 保存栏 */
.save-bar {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  padding: 12px 0;
}
.success-text {
  color: #22c55e;
  font-size: 13px;
}
.icon-button.sm {
  padding: 4px 6px;
}
.icon-button.danger {
  color: #ef4444;
}

/* JSON 校验 */
textarea.has-error {
  border-color: #ef4444;
  box-shadow: 0 0 0 1px #ef4444;
}
.json-error {
  margin-top: 6px;
  padding: 8px 12px;
  background: #fef2f2;
  border: 1px solid #fecaca;
  border-radius: 6px;
  color: #dc2626;
  font-size: 13px;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  word-break: break-all;
}

/* 服务目录 */
.catalog-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.catalog-fields {
  display: flex;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}

/* 日志发现 */
.discovery-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.discovery-fields {
  display: flex;
  gap: 8px;
  flex: 1;
  flex-wrap: wrap;
}

/* 日志清理 */
.cleanup-config {
  padding: 16px;
}
.toggle-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 13px;
  font-weight: 600;
  color: var(--text, #374151);
  cursor: pointer;
}
.toggle-row input[type="checkbox"] {
  width: 16px;
  height: 16px;
  accent-color: #3b82f6;
}
</style>
