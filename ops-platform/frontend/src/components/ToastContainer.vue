<script setup lang="ts">
import { CheckCircle, AlertTriangle, XCircle, Info, X } from "lucide-vue-next";
import { ref, onMounted, onUnmounted } from "vue";
import { bus } from "../events";

interface Toast {
  id: number;
  type: "success" | "error" | "warning" | "info";
  message: string;
}

const toasts = ref<Toast[]>([]);
let nextId = 0;

function addToast(data: { type?: string; message: string }) {
  const t: Toast = {
    id: nextId++,
    type: (data.type as Toast["type"]) || "info",
    message: data.message,
  };
  toasts.value.push(t);
  setTimeout(() => remove(t.id), 4000);
}

function remove(id: number) {
  toasts.value = toasts.value.filter((t) => t.id !== id);
}

const icons: Record<string, any> = {
  success: CheckCircle,
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

onMounted(() => bus.on("toast", addToast));
onUnmounted(() => bus.off("toast", addToast));
</script>

<template>
  <div class="toast-container">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.type">
        <component :is="icons[t.type] || Info" :size="16" />
        <span>{{ t.message }}</span>
        <button class="toast-close" @click="remove(t.id)"><X :size="14" /></button>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  pointer-events: none;
}
.toast {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  border-radius: 8px;
  background: #1e293b;
  border: 1px solid #334155;
  color: #e2e8f0;
  font-size: 13px;
  pointer-events: auto;
  box-shadow: 0 4px 12px rgba(0,0,0,0.3);
  max-width: 380px;
}
.toast.success { border-left: 3px solid #22c55e; }
.toast.error { border-left: 3px solid #ef4444; }
.toast.warning { border-left: 3px solid #f59e0b; }
.toast.info { border-left: 3px solid #3b82f6; }
.toast-close {
  background: none;
  border: none;
  color: #94a3b8;
  cursor: pointer;
  padding: 2px;
  margin-left: auto;
}
.toast-enter-active, .toast-leave-active { transition: all 0.3s ease; }
.toast-enter-from { opacity: 0; transform: translateX(40px); }
.toast-leave-to { opacity: 0; transform: translateX(40px); }
</style>
