import { createRouter, createWebHistory } from "vue-router";
import { isAuthenticated } from "./api";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: "/login", name: "login", component: () => import("./views/LoginView.vue") },
    { path: "/", name: "dashboard", meta: { title: "仪表盘" }, component: () => import("./views/DashboardView.vue") },
    { path: "/agents", name: "agents", meta: { title: "机器列表" }, component: () => import("./views/AgentsView.vue") },
    { path: "/agents/:agentId", name: "agent-detail", meta: { title: "机器详情" }, component: () => import("./views/AgentDetailView.vue") },
    { path: "/alerts", name: "alerts", meta: { title: "告警中心" }, component: () => import("./views/AlertsView.vue") },
    { path: "/configs", name: "configs", meta: { title: "配置中心" }, component: () => import("./views/ConfigsView.vue") },
    { path: "/license", name: "license", meta: { title: "授权管理" }, component: () => import("./views/LicenseView.vue") },
    { path: "/template", name: "template", meta: { title: "模板生成器" }, component: () => import("./views/TemplateGeneratorView.vue") },
    { path: "/notifications", name: "notifications", meta: { title: "通知渠道" }, component: () => import("./views/NotificationsView.vue") },
    { path: "/audit", name: "audit", meta: { title: "审计日志" }, component: () => import("./views/AuditView.vue") },
    { path: "/logs", name: "logs", meta: { title: "日志中心" }, component: () => import("./views/LogsView.vue") },
    { path: "/system-config", name: "system-config", meta: { title: "系统配置" }, component: () => import("./views/SystemConfigView.vue") },
    { path: "/stress-tests", name: "stress-tests", meta: { title: "压力测试" }, component: () => import("./views/StressTestsView.vue") },
    { path: "/stress-tests/:testId", name: "stress-test-detail", meta: { title: "测试详情" }, component: () => import("./views/StressTestDetailView.vue") },
    { path: "/stress-tests/:testId/report", name: "stress-test-report", meta: { title: "测试报告" }, component: () => import("./views/StressTestReportView.vue") },
    { path: "/agent-groups", name: "agent-groups", meta: { title: "分组管理" }, component: () => import("./views/AgentGroupsView.vue") },
    { path: "/remote-commands", name: "remote-commands", meta: { title: "远程命令" }, component: () => import("./views/RemoteCommandsView.vue") },
    { path: "/file-distributions", name: "file-distributions", meta: { title: "文件分发" }, component: () => import("./views/FileDistributionsView.vue") },
    { path: "/deployments", name: "deployments", meta: { title: "软件部署" }, component: () => import("./views/DeploymentsView.vue") },
    { path: "/ai-settings", name: "ai-settings", meta: { title: "AI 设置" }, component: () => import("./views/AiSettingsView.vue") },
    { path: "/:pathMatch(.*)*", name: "not-found", component: () => import("./views/NotFoundView.vue") }
  ]
});

router.beforeEach((to) => {
  if (to.name !== "login" && !isAuthenticated()) return { name: "login" };
  if (to.name === "login" && isAuthenticated()) return { name: "dashboard" };
  return true;
});

export default router;
