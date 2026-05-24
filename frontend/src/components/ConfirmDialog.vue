<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";

defineProps<{
  visible: boolean;
  title?: string;
  message: string;
  confirmText?: string;
  cancelText?: string;
  danger?: boolean;
}>();

const emit = defineEmits<{
  confirm: [];
  cancel: [];
}>();
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div v-if="visible" class="confirm-overlay" @click.self="emit('cancel')">
        <div class="confirm-box">
          <div class="confirm-icon">
            <AlertTriangle :size="28" />
          </div>
          <h3>{{ title || "确认操作" }}</h3>
          <p>{{ message }}</p>
          <div class="confirm-actions">
            <button class="btn" @click="emit('cancel')">{{ cancelText || "取消" }}</button>
            <button class="btn" :class="danger ? 'danger' : 'primary'" @click="emit('confirm')">
              {{ confirmText || "确定" }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.confirm-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 200;
}
.confirm-box {
  background: #1e293b;
  border: 1px solid #334155;
  border-radius: 12px;
  padding: 24px;
  width: 380px;
  text-align: center;
}
.confirm-icon {
  color: #f59e0b;
  margin-bottom: 12px;
}
.confirm-box h3 {
  margin: 0 0 8px;
  font-size: 16px;
}
.confirm-box p {
  margin: 0 0 20px;
  color: #94a3b8;
  font-size: 14px;
  line-height: 1.5;
}
.confirm-actions {
  display: flex;
  gap: 8px;
  justify-content: center;
}
.btn.danger {
  background: #ef4444;
  color: #fff;
  border: none;
}
.btn.danger:hover {
  background: #dc2626;
}
.fade-enter-active, .fade-leave-active { transition: opacity 0.2s; }
.fade-enter-from, .fade-leave-to { opacity: 0; }
</style>
