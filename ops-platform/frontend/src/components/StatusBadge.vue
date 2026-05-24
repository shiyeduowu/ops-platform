<script setup lang="ts">
const props = defineProps<{
  value: string;
}>();

const labels: Record<string, string> = {
  online: "在线",
  offline: "离线",
  active: "有效",
  paused: "暂停",
  expired: "已过期",
  open: "未处理",
  acknowledged: "已确认",
  resolved: "已恢复",
  info: "提示",
  warning: "警告",
  critical: "严重",
  error: "异常",
  unknown: "未知",
  draft: "草稿",
  pending: "等待中",
  running: "运行中",
  completed: "已完成",
  failed: "失败",
  cancelled: "已取消",
  downloading: "下载中",
  uploading: "上传中",
  skipped: "已跳过",
};
</script>

<template>
  <span class="status-badge" :class="`status-${props.value}`">
    {{ labels[props.value] || props.value }}
  </span>
</template>
