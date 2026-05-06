from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class TaskWebSocketManager:
    def __init__(self) -> None:
        self._connections: dict[int, set[WebSocket]] = defaultdict(set)

    async def connect(self, task_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[task_id].add(websocket)

    def disconnect(self, task_id: int, websocket: WebSocket) -> None:
        sockets = self._connections.get(task_id)
        if not sockets:
            return
        sockets.discard(websocket)
        if not sockets:
            self._connections.pop(task_id, None)

    async def broadcast(self, task_id: int, payload: dict[str, Any]) -> None:
        sockets = list(self._connections.get(task_id, set()))
        for websocket in sockets:
            try:
                await websocket.send_json(payload)
            except Exception:
                self.disconnect(task_id, websocket)


task_ws_manager = TaskWebSocketManager()
