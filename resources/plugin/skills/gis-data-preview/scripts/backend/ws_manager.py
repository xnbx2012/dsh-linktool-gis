import asyncio
import json
from typing import Set
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._connections: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.add(ws)

    def disconnect(self, ws: WebSocket):
        self._connections.discard(ws)

    async def broadcast(self, message: dict):
        if not self._connections:
            return
        dead = set()
        payload = json.dumps(message, ensure_ascii=False)
        for ws in self._connections:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.add(ws)
        self._connections -= dead

    @property
    def connection_count(self):
        return len(self._connections)


ws_manager = WebSocketManager()
