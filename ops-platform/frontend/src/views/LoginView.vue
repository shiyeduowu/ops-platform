<script setup lang="ts">
import { LockKeyhole, MonitorCog } from "lucide-vue-next";
import { ref } from "vue";
import { useRouter } from "vue-router";
import { api, saveSession } from "../api";

const router = useRouter();
const username = ref("");
const password = ref("");
const loading = ref(false);
const error = ref("");

async function submit() {
  loading.value = true;
  error.value = "";
  try {
    const token = await api.login(username.value, password.value);
    saveSession(token);
    router.push("/");
  } catch (err) {
    error.value = err instanceof Error ? err.message : "登录失败";
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <div class="login-brand">
        <div class="brand-mark large">
          <MonitorCog :size="28" />
        </div>
        <div>
          <h1>运维平台</h1>
          <p>Agent + 控制平面</p>
        </div>
      </div>

      <form class="login-form" @submit.prevent="submit">
        <label>
          <span>用户名</span>
          <input v-model="username" autocomplete="username" />
        </label>
        <label>
          <span>密码</span>
          <input v-model="password" type="password" autocomplete="current-password" />
        </label>
        <p v-if="error" class="form-error">{{ error }}</p>
        <button class="primary-button" type="submit" :disabled="loading">
          <LockKeyhole :size="18" />
          <span>{{ loading ? "登录中" : "登录" }}</span>
        </button>
      </form>
    </section>

    <section class="login-side">
      <div class="metric-strip">
        <span>多租户</span>
        <span>配置影子</span>
        <span>实时数据流</span>
      </div>
      <div class="login-map">
        <div class="node active">Agent</div>
        <div class="line"></div>
        <div class="node">网关</div>
        <div class="line"></div>
        <div class="node">PostgreSQL</div>
      </div>
    </section>
  </main>
</template>
