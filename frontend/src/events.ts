/**
 * 全局事件总线 — 用于 Dashboard WebSocket 事件分发
 */
type Handler = (data: any) => void;

class EventBus {
  private _handlers = new Map<string, Set<Handler>>();

  on(event: string, handler: Handler) {
    if (!this._handlers.has(event)) {
      this._handlers.set(event, new Set());
    }
    this._handlers.get(event)!.add(handler);
  }

  off(event: string, handler: Handler) {
    this._handlers.get(event)?.delete(handler);
  }

  emit(event: string, data: any) {
    this._handlers.get(event)?.forEach((h) => h(data));
  }
}

export const bus = new EventBus();

export function toast(message: string, type: "success" | "error" | "warning" | "info" = "success") {
  bus.emit("toast", { message, type });
}
