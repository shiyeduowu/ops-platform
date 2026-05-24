<script setup lang="ts">
import { Bot, Send, X, Loader2, Wrench, ChevronDown } from "lucide-vue-next";
import { nextTick, ref, watch } from "vue";
import { getApiBase, getToken } from "../../api";

const props = defineProps<{ open: boolean }>();
const emit = defineEmits<{ close: [] }>();

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCallEvent[];
  degraded?: boolean;
}
interface ToolCallEvent {
  toolName: string;
  resultPreview?: string;
}

const input = ref("");
const messages = ref<ChatMessage[]>([]);
const loading = ref(false);
const scrollRef = ref<HTMLDivElement | null>(null);

function scrollToBottom() {
  nextTick(() => {
    if (scrollRef.value) scrollRef.value.scrollTop = scrollRef.value.scrollHeight;
  });
}

async function send() {
  const text = input.value.trim();
  if (!text || loading.value) return;

  messages.value.push({ role: "user", content: text });
  input.value = "";
  loading.value = true;
  scrollToBottom();

  const assistantMsg: ChatMessage = { role: "assistant", content: "", toolCalls: [] };
  messages.value.push(assistantMsg);

  try {
    const history = messages.value
      .slice(0, -1)
      .filter((m) => m.role === "user" || m.role === "assistant")
      .map((m) => ({ role: m.role, content: m.content }));

    const resp = await fetch(`${getApiBase()}/api/v1/aiops/chat`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ message: text, history }),
    });

    if (!resp.ok) {
      assistantMsg.content = `请求失败: ${resp.status}`;
      return;
    }

    const reader = resp.body?.getReader();
    if (!reader) return;

    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const data = line.slice(6).trim();
        if (data === "[DONE]") continue;

        try {
          const parsed = JSON.parse(data);
          if (parsed.type === "tool_call") {
            assistantMsg.toolCalls = assistantMsg.toolCalls || [];
            assistantMsg.toolCalls.push({ toolName: parsed.tool_name });
          } else if (parsed.type === "tool_result") {
            const last = assistantMsg.toolCalls?.[assistantMsg.toolCalls.length - 1];
            if (last) last.resultPreview = parsed.result_preview;
          } else if (parsed.role === "assistant") {
            assistantMsg.content = parsed.content || "";
            assistantMsg.degraded = parsed.degraded || false;
          }
          scrollToBottom();
        } catch {
          // skip unparseable lines
        }
      }
    }
  } catch (e) {
    assistantMsg.content = `连接错误: ${e}`;
  } finally {
    loading.value = false;
    scrollToBottom();
  }
}

function handleKey(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    send();
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="slide">
      <div v-if="open" class="ai-overlay" @click.self="emit('close')">
        <div class="ai-panel">
          <!-- Header -->
          <div class="ai-header">
            <div class="ai-header-title">
              <Bot :size="20" />
              <span>AI 运维助手</span>
            </div>
            <button class="icon-btn" @click="emit('close')">
              <X :size="18" />
            </button>
          </div>

          <!-- Messages -->
          <div ref="scrollRef" class="ai-messages">
            <div v-if="messages.length === 0" class="ai-empty">
              <Bot :size="40" />
              <p>你好！我是 AI 运维助手</p>
              <p class="sub">可以问我关于主机状态、告警、部署等问题</p>
            </div>

            <div v-for="(msg, i) in messages" :key="i" :class="['ai-msg', msg.role]">
              <div class="ai-msg-content">
                {{ msg.content }}
              </div>

              <!-- Tool calls -->
              <div v-if="msg.toolCalls && msg.toolCalls.length > 0" class="ai-tools">
                <div v-for="(tc, j) in msg.toolCalls" :key="j" class="ai-tool-item">
                  <Wrench :size="14" />
                  <span>{{ tc.toolName }}</span>
                  <span v-if="tc.resultPreview" class="ai-tool-done">done</span>
                  <Loader2 v-else :size="12" class="spin" />
                </div>
              </div>

              <div v-if="msg.degraded" class="ai-degraded">AI 功能受限</div>
            </div>

            <div v-if="loading && messages[messages.length - 1]?.content === ''" class="ai-typing">
              <Loader2 :size="16" class="spin" />
              <span>思考中...</span>
            </div>
          </div>

          <!-- Input -->
          <div class="ai-input-area">
            <textarea
              v-model="input"
              class="ai-input"
              placeholder="输入问题... (Enter 发送)"
              rows="2"
              @keydown="handleKey"
            />
            <button class="ai-send" :disabled="!input.trim() || loading" @click="send">
              <Send :size="18" />
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ai-overlay {
  position: fixed;
  inset: 0;
  z-index: 1000;
  background: rgba(0, 0, 0, 0.3);
  display: flex;
  justify-content: flex-end;
}
.ai-panel {
  width: 420px;
  max-width: 100vw;
  background: var(--surface, #fff);
  display: flex;
  flex-direction: column;
  box-shadow: -4px 0 24px rgba(0, 0, 0, 0.15);
}
.ai-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border, #e5e7eb);
}
.ai-header-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
}
.icon-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--text-secondary, #6b7280);
  padding: 4px;
  border-radius: 4px;
}
.icon-btn:hover {
  background: var(--hover, #f3f4f6);
}
.ai-messages {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ai-empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  height: 100%;
  color: var(--text-secondary, #6b7280);
  gap: 8px;
}
.ai-empty .sub {
  font-size: 0.85em;
  opacity: 0.7;
}
.ai-msg {
  max-width: 90%;
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 0.9em;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.ai-msg.user {
  align-self: flex-end;
  background: var(--primary, #3b82f6);
  color: #fff;
  border-bottom-right-radius: 4px;
}
.ai-msg.assistant {
  align-self: flex-start;
  background: var(--surface-secondary, #f3f4f6);
  border-bottom-left-radius: 4px;
}
.ai-tools {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.ai-tool-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.8em;
  opacity: 0.7;
}
.ai-tool-done {
  color: #10b981;
  font-size: 0.75em;
}
.ai-degraded {
  margin-top: 6px;
  font-size: 0.75em;
  color: #f59e0b;
}
.ai-typing {
  display: flex;
  align-items: center;
  gap: 8px;
  color: var(--text-secondary, #6b7280);
  font-size: 0.85em;
}
.ai-input-area {
  display: flex;
  gap: 8px;
  padding: 12px 16px;
  border-top: 1px solid var(--border, #e5e7eb);
}
.ai-input {
  flex: 1;
  border: 1px solid var(--border, #e5e7eb);
  border-radius: 8px;
  padding: 8px 12px;
  resize: none;
  font-size: 0.9em;
  font-family: inherit;
  background: var(--surface, #fff);
  color: var(--text, #111);
}
.ai-input:focus {
  outline: none;
  border-color: var(--primary, #3b82f6);
}
.ai-send {
  background: var(--primary, #3b82f6);
  color: #fff;
  border: none;
  border-radius: 8px;
  padding: 8px 12px;
  cursor: pointer;
  display: flex;
  align-items: center;
}
.ai-send:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.spin {
  animation: spin 1s linear infinite;
}
@keyframes spin {
  to {
    transform: rotate(360deg);
  }
}
.slide-enter-active,
.slide-leave-active {
  transition: transform 0.3s ease;
}
.slide-enter-from .ai-panel,
.slide-leave-to .ai-panel {
  transform: translateX(100%);
}
</style>
