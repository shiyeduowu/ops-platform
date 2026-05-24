<script setup lang="ts">
import { Inbox } from "lucide-vue-next";

defineProps<{
  title: string;
  description?: string;
}>();
</script>

<template>
  <div class="empty-state">
    <Inbox :size="28" />
    <span>{{ title }}</span>
    <small v-if="description">{{ description }}</small>
  </div>
</template>
