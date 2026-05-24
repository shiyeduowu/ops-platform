<script setup lang="ts">
import {
  Search,
  RefreshCw,
  FileText,
  BarChart3,
  Clock,
  Server,
  Layers
} from "lucide-vue-next";
import { onMounted, ref } from "vue";
import { api } from "../api";
import EmptyState from "../components/EmptyState.vue";
import type { LogItem, LogSearchResult, LogStats } from "../types";

const logs = ref<LogItem[]>([]);
const searchResult = ref<LogSearchResult | null>(null);
const stats = ref<LogStats | null>(null);
const loading = ref(false);
const error = ref("");
const keyword = ref("");
const searching = ref(false);
const statsHours = ref(24);

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const [logsRes, statsRes] = await Promise.all([
      api.logs("?limit=100"),
      api.logStats(statsHours.value),
    ]);
    logs.value = logsRes;
    stats.value = statsRes;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

async function search() {
  if (!keyword.value.trim()) {
    searchResult.value = null;
    return;
  }
  searching.value = true;
  error.value = "";
  try {
    searchResult.value = await api.logSearch(keyword.value);
  } catch (err) {
    error.value = err instanceof Error ? err.message : "搜索失败";
  } finally {
    searching.value = false;
  }
}

function highlightHtml(text: string) {
  return text.replace(/\*\*(.*?)\*\*/g, '<mark>$1</mark>');
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <!-- 统计卡片 -->
    <div v-if="stats" class="stat-row">
      <div class="stat-card">
        <div class="stat-icon" style="background:#3b82f618;color:#3b82f6"><FileText :size="20" /></div>
        <div>
          <p class="stat-label">{{ stats.hours }}小时内日志</p>
          <p class="stat-value">{{ stats.total }}</p>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:#22c55e18;color:#22c55e"><Layers :size="20" /></div>
        <div>
          <p class="stat-label">服务数</p>
          <p class="stat-value">{{ Object.keys(stats.by_service).length }}</p>
        </div>
      </div>
      <div class="stat-card">
        <div class="stat-icon" style="background:#f59e0b18;color:#f59e0b"><Server :size="20" /></div>
        <div>
          <p class="stat-label">Agent数</p>
          <p class="stat-value">{{ Object.keys(stats.top_agents).length }}</p>
        </div>
      </div>
    </div>

    <!-- 搜索栏 -->
    <div class="search-bar">
      <div class="search-input-wrap">
        <Search :size="17" />
        <input
          v-model="keyword"
          type="text"
          placeholder="搜索日志内容..."
          @keyup.enter="search"
        />
      </div>
      <button class="icon-button primary" type="button" :disabled="searching" @click="search">
        <Search :size="17" />
        <span>{{ searching ? "搜索中..." : "搜索" }}</span>
      </button>
      <button v-if="searchResult" class="icon-button" type="button" @click="searchResult = null; keyword = ''">
        <span>清除</span>
      </button>
      <button class="icon-button" type="button" @click="load">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <!-- 搜索结果 -->
    <section v-if="searchResult" class="panel">
      <div class="panel-heading">
        <h2>搜索结果</h2>
        <span>共 {{ searchResult.total }} 条匹配</span>
      </div>
      <EmptyState v-if="!searchResult.logs.length" title="无匹配结果" />
      <div v-else class="log-list">
        <div v-for="item in searchResult.logs" :key="item.id" class="log-entry">
          <div class="log-meta">
            <code>{{ item.agent_id }}</code>
            <span class="log-service">{{ item.service_key }}</span>
            <span class="log-time">{{ item.created_at ? new Date(item.created_at).toLocaleString() : '-' }}</span>
          </div>
          <div class="log-content" v-html="highlightHtml(item.highlighted_content)"></div>
        </div>
      </div>
    </section>

    <!-- 服务分布 -->
    <section v-if="stats && Object.keys(stats.by_service).length" class="panel">
      <div class="panel-heading">
        <h2>服务分布</h2>
      </div>
      <div class="bar-chart">
        <div v-for="(count, service) in stats.by_service" :key="service" class="bar-row">
          <span class="bar-label">{{ service }}</span>
          <div class="bar-track">
            <div
              class="bar-fill"
              :style="{ width: Math.min(100, (count / stats.total) * 100) + '%' }"
            ></div>
          </div>
          <span class="bar-value">{{ count }}</span>
        </div>
      </div>
    </section>

    <!-- 最新日志 -->
    <section class="panel">
      <div class="panel-heading">
        <h2>最新日志</h2>
        <span>{{ logs.length }} 条</span>
      </div>
      <div v-if="loading" class="loading-row">加载中</div>
      <EmptyState v-else-if="!logs.length" title="暂无日志" />
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>时间</th>
              <th>Agent</th>
              <th>服务</th>
              <th>内容</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="log in logs" :key="log.id">
              <td class="time-cell">{{ new Date(log.created_at).toLocaleString() }}</td>
              <td><code>{{ log.agent_id }}</code></td>
              <td>{{ log.service_key }}</td>
              <td class="content-cell">{{ log.content.slice(0, 200) }}{{ log.content.length > 200 ? '...' : '' }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  </section>
</template>

<style scoped>
.stat-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 12px;
}
.stat-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px;
  border-radius: 10px;
  background: var(--surface, #fff);
  border: 1px solid var(--border, #e5e7eb);
}
.stat-icon {
  width: 40px;
  height: 40px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}
.stat-label {
  font-size: 12px;
  opacity: 0.6;
  margin: 0;
}
.stat-value {
  font-size: 20px;
  font-weight: 700;
  margin: 0;
}
.search-bar {
  display: flex;
  align-items: center;
  gap: 8px;
}
.search-input-wrap {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 8px;
  background: var(--surface, #fff);
}
.search-input-wrap input {
  border: none;
  outline: none;
  flex: 1;
  font-size: 14px;
  background: transparent;
}
.icon-button.primary {
  background: #3b82f6;
  color: #fff;
  border: none;
}
.icon-button.primary:hover {
  background: #2563eb;
}
.log-list {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background: var(--border, #e5e7eb);
}
.log-entry {
  padding: 12px 16px;
  background: var(--surface, #fff);
}
.log-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 6px;
  font-size: 12px;
}
.log-service {
  opacity: 0.6;
}
.log-time {
  margin-left: auto;
  opacity: 0.5;
}
.log-content {
  font-size: 13px;
  line-height: 1.5;
  word-break: break-all;
}
.log-content :deep(mark) {
  background: #fef08a;
  color: #1e293b;
  padding: 1px 2px;
  border-radius: 2px;
}
.bar-chart {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.bar-row {
  display: flex;
  align-items: center;
  gap: 10px;
}
.bar-label {
  width: 120px;
  font-size: 12px;
  text-align: right;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bar-track {
  flex: 1;
  height: 18px;
  background: var(--bg, #f1f5f9);
  border-radius: 4px;
  overflow: hidden;
}
.bar-fill {
  height: 100%;
  background: linear-gradient(90deg, #3b82f6, #60a5fa);
  border-radius: 4px;
  transition: width 0.5s ease;
  min-width: 2px;
}
.bar-value {
  width: 40px;
  font-size: 12px;
  font-weight: 600;
}
.time-cell {
  font-size: 12px;
  white-space: nowrap;
}
.content-cell {
  font-size: 12px;
  max-width: 400px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
