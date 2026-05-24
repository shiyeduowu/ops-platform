<script setup lang="ts">
import { Home } from "lucide-vue-next";
import { useRouter } from "vue-router";

const router = useRouter();
</script>

<template>
  <div class="not-found">
    <h1>404</h1>
    <p>页面不存在</p>
    <button class="btn primary" @click="router.push('/')">
      <Home :size="16" /> 返回首页
    </button>
  </div>
</template>

<style scoped>
.not-found {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  min-height: 60vh;
  gap: 12px;
}
.not-found h1 {
  font-size: 72px;
  font-weight: 700;
  color: #334155;
  margin: 0;
}
.not-found p {
  font-size: 18px;
  color: #94a3b8;
  margin: 0 0 16px;
}
</style>
