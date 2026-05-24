<script setup lang="ts">
import { ChevronLeft, ChevronRight } from "lucide-vue-next";
import { computed } from "vue";

const props = defineProps<{
  total: number;
  page: number;
  pageSize: number;
}>();

const emit = defineEmits<{
  (e: "update:page", page: number): void;
}>();

const totalPages = computed(() => Math.max(1, Math.ceil(props.total / props.pageSize)));
const from = computed(() => props.total === 0 ? 0 : (props.page - 1) * props.pageSize + 1);
const to = computed(() => Math.min(props.page * props.pageSize, props.total));

function go(p: number) {
  if (p >= 1 && p <= totalPages.value) emit("update:page", p);
}
</script>

<template>
  <div v-if="total > 0" class="pagination-bar">
    <span class="page-info">{{ from }}–{{ to }} / {{ total }}</span>
    <button class="page-btn" :disabled="page <= 1" @click="go(page - 1)"><ChevronLeft :size="16" /></button>
    <button class="page-btn" :disabled="page >= totalPages" @click="go(page + 1)"><ChevronRight :size="16" /></button>
  </div>
</template>

<style scoped>
.pagination-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  justify-content: flex-end;
  padding: 8px 0;
  font-size: 13px;
  color: var(--muted, #94a3b8);
}
.page-btn {
  background: var(--surface, #1e293b);
  border: 1px solid var(--line, #334155);
  border-radius: 6px;
  padding: 4px 8px;
  color: var(--text, #e2e8f0);
  cursor: pointer;
  display: flex;
  align-items: center;
}
.page-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.page-btn:not(:disabled):hover {
  background: var(--surface-alt, #334155);
}
</style>
