<script setup lang="ts">
import {
  Activity,
  Bell,
  Cog,
  FileSpreadsheet,
  FileText,
  Gauge,
  KeyRound,
  LogOut,
  MonitorCog,
  Package,
  ScrollText,
  Send,
  Server,
  Settings2,
  ShieldCheck,
  Terminal,
  Upload,
  Users,
  Zap
} from "lucide-vue-next";
import { computed, onMounted, onUnmounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { clearSession, connectDashboardSocket } from "./api";
import { bus } from "./events";
import ToastContainer from "./components/ToastContainer.vue";

const route = useRoute();
const router = useRouter();
const isLogin = computed(() => route.name === "login");
const userRole = computed(() => localStorage.getItem("ops-platform-role") || "");
const isAdmin = computed(() => ["owner", "admin"].includes(userRole.value));

interface NavItem { to: string; label: string; icon: any }
interface NavGroup { label: string; items: NavItem[] }

const navGroups = computed<NavGroup[]>(() => {
  const groups: NavGroup[] = [
    {
      label: "概览",
      items: [
        { to: "/", label: "仪表盘", icon: Gauge },
        { to: "/agents", label: "机器", icon: Server },
        { to: "/alerts", label: "告警", icon: Bell },
        { to: "/agent-groups", label: "分组管理", icon: Users },
      ],
    },
    {
      label: "监控",
      items: [
        { to: "/configs", label: "配置", icon: Settings2 },
        { to: "/logs", label: "日志", icon: FileText },
        { to: "/notifications", label: "通知渠道", icon: Send },
        { to: "/audit", label: "审计", icon: ScrollText },
      ],
    },
    {
      label: "运维",
      items: [
        { to: "/stress-tests", label: "压力测试", icon: Zap },
        { to: "/remote-commands", label: "远程命令", icon: Terminal },
        { to: "/file-distributions", label: "文件分发", icon: Upload },
        { to: "/deployments", label: "软件部署", icon: Package },
      ],
    },
    {
      label: "系统",
      items: [
        { to: "/license", label: "授权", icon: ShieldCheck },
        { to: "/template", label: "模板生成", icon: FileSpreadsheet },
      ],
    },
  ];
  if (isAdmin.value) {
    groups[groups.length - 1].items.push({ to: "/system-config", label: "系统配置", icon: Cog });
  }
  return groups;
});

const unreadAlerts = ref(0);
let dashWs: WebSocket | null = null;

onMounted(() => {
  const token = localStorage.getItem("ops-platform-token");
  if (!token) return;
  dashWs = connectDashboardSocket((msg: any) => {
    if (msg?.event === "alert") {
      unreadAlerts.value++;
      bus.emit("alert", msg.alert);
    } else if (msg?.event === "task_completed") {
      bus.emit("task_completed", msg);
    }
  });
});

onUnmounted(() => {
  if (dashWs && (dashWs as any)._opsClose) {
    (dashWs as any)._opsClose();
  }
});

function logout() {
  if (dashWs && (dashWs as any)._opsClose) {
    (dashWs as any)._opsClose();
  }
  clearSession();
  router.push("/login");
}
</script>

<template>
  <RouterView v-if="isLogin" />
  <template v-else>
  <ToastContainer />
  <div class="app-shell">
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-mark">
          <MonitorCog :size="22" />
        </div>
        <div>
          <strong>运维平台</strong>
          <span>控制台</span>
        </div>
      </div>

      <nav class="nav-list" aria-label="Main navigation">
        <div v-for="group in navGroups" :key="group.label" class="nav-group">
          <span class="nav-group-label">{{ group.label }}</span>
          <RouterLink v-for="item in group.items" :key="item.to" :to="item.to" class="nav-item" @click="item.to === '/alerts' && (unreadAlerts = 0)">
            <span class="nav-icon-wrap">
              <component :is="item.icon" :size="18" />
              <span v-if="item.to === '/alerts' && unreadAlerts > 0" class="badge">{{ unreadAlerts > 9 ? "9+" : unreadAlerts }}</span>
            </span>
            <span>{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-footer">
        <div class="mini-status">
          <Activity :size="16" />
          <span>演示运行中</span>
        </div>
        <button class="icon-button wide" type="button" title="退出登录" @click="logout">
          <LogOut :size="17" />
          <span>退出登录</span>
        </button>
      </div>
    </aside>

    <main class="main">
      <header class="topbar">
        <div>
          <p class="eyebrow">企业级运维 SaaS</p>
          <h1>{{ String(route.meta.title || route.name || "Dashboard") }}</h1>
        </div>
        <div class="topbar-actions">
          <div class="pill">
            <KeyRound :size="16" />
            <span>已登录会话</span>
          </div>
        </div>
      </header>
      <RouterView v-slot="{ Component }">
        <transition name="page-fade" mode="out-in">
          <component :is="Component" />
        </transition>
      </RouterView>
    </main>
  </div>
  </template>
</template>
