<script setup lang="ts">
import { Download, RefreshCw, Search } from "lucide-vue-next";
import { computed, onMounted, ref } from "vue";
import { RouterLink } from "vue-router";
import { api } from "../api";
import { exportCsv } from "../export";
import EmptyState from "../components/EmptyState.vue";
import PaginationBar from "../components/PaginationBar.vue";
import StatusBadge from "../components/StatusBadge.vue";
import type { Agent } from "../types";

const agents = ref<Agent[]>([]);
const query = ref("");
const loading = ref(false);
const error = ref("");

// 分页
const page = ref(1);
const pageSize = 20;
const total = ref(0);

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  if (!q) return agents.value;
  return agents.value.filter((agent) =>
    [agent.hostname, agent.agent_id, agent.ip || "", agent.status].some((item) => item.toLowerCase().includes(q))
  );
});

async function load() {
  loading.value = true;
  error.value = "";
  try {
    const offset = (page.value - 1) * pageSize;
    const params = `?limit=${pageSize}&offset=${offset}`;
    const res = await api.agents(params);
    agents.value = res.items ?? res;
    total.value = res.total ?? agents.value.length;
  } catch (err) {
    error.value = err instanceof Error ? err.message : "加载失败";
  } finally {
    loading.value = false;
  }
}

function onPageChange(p: number) {
  page.value = p;
  load();
}

function exportData() {
  exportCsv(
    "agents.csv",
    ["agent_id", "hostname", "ip", "status", "version", "last_seen"],
    filtered.value.map((a) => [a.agent_id, a.hostname, a.ip || "", a.status, a.version, a.last_seen ? new Date(a.last_seen).toLocaleString() : ""]),
  );
}

onMounted(load);
</script>

<template>
  <section class="content-stack">
    <div class="toolbar">
      <label class="search-box">
        <Search :size="17" />
        <input v-model="query" placeholder="搜索机器" />
      </label>
      <button class="icon-button" type="button" title="刷新机器列表" @click="load">
        <RefreshCw :size="17" />
        <span>刷新</span>
      </button>
      <button class="icon-button" type="button" @click="exportData">
        <Download :size="17" />
        <span>导出</span>
      </button>
    </div>

    <div v-if="error" class="alert-line">{{ error }}</div>

    <section class="panel">
      <div class="panel-heading">
        <h2>机器列表</h2>
        <span>{{ filtered.length }} 条记录</span>
      </div>
      <div v-if="loading" class="loading-row">加载中</div>
      <EmptyState v-else-if="!filtered.length" title="没有找到机器" />
      <div v-else class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>主机名</th>
              <th>Agent ID</th>
              <th>IP</th>
              <th>状态</th>
              <th>版本</th>
              <th>最后心跳</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="agent in filtered" :key="agent.agent_id">
              <td><RouterLink class="strong-link" :to="`/agents/${agent.agent_id}`">{{ agent.hostname }}</RouterLink></td>
              <td><code>{{ agent.agent_id }}</code></td>
              <td>{{ agent.ip || "-" }}</td>
              <td><StatusBadge :value="agent.status" /></td>
              <td>{{ agent.version }}</td>
              <td>{{ agent.last_seen ? new Date(agent.last_seen).toLocaleString() : "-" }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <PaginationBar v-if="total > pageSize" :page="page" :page-size="pageSize" :total="total" @update:page="onPageChange" />
    </section>
  </section>
</template>
