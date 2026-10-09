import asyncio
from collections import defaultdict
from typing import Any

from fastapi import WebSocket


class WebSocketManager:
    def __init__(self) -> None:
        self.market_connections: set[WebSocket] = set()
        self.status_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._snapshot: dict[str, Any] = defaultdict(dict)

    async def connect_market(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.market_connections.add(ws)

    async def connect_status(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self.status_connections.add(ws)

    async def disconnect_market(self, ws: WebSocket) -> None:
        async with self._lock:
            self.market_connections.discard(ws)

    async def disconnect_status(self, ws: WebSocket) -> None:
        async with self._lock:
            self.status_connections.discard(ws)

    async def broadcast_market(self, event: dict[str, Any]) -> None:
        symbol = event.get("data", {}).get("option_symbol")
        if symbol:
            self._snapshot[symbol] = event.get("data", {})
        await self._broadcast(self.market_connections, event)

    async def broadcast_status(self, event: dict[str, Any]) -> None:
        await self._broadcast(self.status_connections, event)

    async def send_snapshot(self, ws: WebSocket) -> None:
        await ws.send_json({"type": "snapshot", "data": list(self._snapshot.values())})

    async def _broadcast(self, conns: set[WebSocket], payload: dict[str, Any]) -> None:
        dead: list[WebSocket] = []
        for ws in conns:
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            conns.discard(ws)


manager = WebSocketManager()
