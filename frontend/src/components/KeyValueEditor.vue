<script setup lang="ts">
import { Plus, X } from "lucide-vue-next";

const props = defineProps<{
  modelValue: Record<string, string>;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}>();

const emit = defineEmits<{
  (e: "update:modelValue", value: Record<string, string>): void;
}>();

function addEntry() {
  emit("update:modelValue", { ...props.modelValue, "": "" });
}

function removeEntry(key: string) {
  const copy = { ...props.modelValue };
  delete copy[key];
  emit("update:modelValue", copy);
}

function updateKey(oldKey: string, newKey: string) {
  const entries = Object.entries(props.modelValue);
  const updated: Record<string, string> = {};
  for (const [k, v] of entries) {
    if (k === oldKey) {
      updated[newKey] = v;
    } else {
      updated[k] = v;
    }
  }
  emit("update:modelValue", updated);
}

function updateValue(key: string, value: string) {
  emit("update:modelValue", { ...props.modelValue, [key]: value });
}
</script>

<template>
  <div class="kv-editor">
    <div v-for="(_, key, idx) in modelValue" :key="idx" class="kv-row">
      <input
        class="kv-key"
        :value="key"
        :placeholder="keyPlaceholder || 'Key'"
        @input="updateKey(key, ($event.target as HTMLInputElement).value)"
      />
      <input
        class="kv-val"
        :value="modelValue[key]"
        :placeholder="valuePlaceholder || 'Value'"
        @input="updateValue(key, ($event.target as HTMLInputElement).value)"
      />
      <button class="kv-remove" type="button" @click="removeEntry(key)">
        <X :size="14" />
      </button>
    </div>
    <button class="kv-add" type="button" @click="addEntry">
      <Plus :size="13" />
      添加
    </button>
  </div>
</template>

<style scoped>
.kv-editor {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kv-row {
  display: flex;
  gap: 6px;
}
.kv-key {
  flex: 1;
  padding: 7px 10px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg, #f9fafb);
  font-family: monospace;
}
.kv-val {
  flex: 2;
  padding: 7px 10px;
  border: 1px solid var(--border, #d1d5db);
  border-radius: 6px;
  font-size: 13px;
  background: var(--bg, #f9fafb);
  font-family: monospace;
}
.kv-remove {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 30px;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  color: #ef4444;
}
.kv-remove:hover {
  background: #fef2f2;
}
.kv-add {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 6px 10px;
  border: 1px dashed var(--border, #d1d5db);
  border-radius: 6px;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: var(--text, #374151);
  align-self: flex-start;
}
.kv-add:hover {
  background: var(--bg, #f9fafb);
}
</style>
