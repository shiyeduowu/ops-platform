from __future__ import annotations

from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[str, list[WebSocket]] = defaultdict(list)

    async def connect(self, agent_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[agent_id].append(websocket)

    def disconnect(self, agent_id: str, websocket: WebSocket) -> None:
        connections = self._connections.get(agent_id, [])
        if websocket in connections:
            connections.remove(websocket)
        if not connections and agent_id in self._connections:
            del self._connections[agent_id]

    async def broadcast(self, agent_id: str, payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for websocket in list(self._connections.get(agent_id, [])):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead.append(websocket)
        for websocket in dead:
            self.disconnect(agent_id, websocket)

    async def broadcast_all(self, payload: dict[str, Any]) -> None:
        """向所有已连接的 WebSocket 客户端广播消息"""
        dead: list[tuple[str, WebSocket]] = []
        for agent_id, sockets in list(self._connections.items()):
            for websocket in list(sockets):
                try:
                    await websocket.send_json(payload)
                except Exception:
                    dead.append((agent_id, websocket))
        for agent_id, websocket in dead:
            self.disconnect(agent_id, websocket)

    def count(self, agent_id: str | None = None) -> int:
        if agent_id is not None:
            return len(self._connections.get(agent_id, []))
        return sum(len(items) for items in self._connections.values())


ws_manager = WebSocketManager()

