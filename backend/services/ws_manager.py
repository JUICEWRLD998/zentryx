"""
WebSocket connection manager.

Tracks all connected frontend clients and provides a broadcast method
to push trade events to every active connection.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self) -> None:
        self._connections: list[WebSocket] = []
        self._lock = asyncio.Lock()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._connections.append(ws)
        logger.info("WS client connected. Total: %d", len(self._connections))

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            try:
                self._connections.remove(ws)
            except ValueError:
                pass
        logger.info("WS client disconnected. Total: %d", len(self._connections))

    async def broadcast(self, data: dict[str, Any]) -> None:
        """Send JSON payload to all connected clients, dropping dead connections."""
        if not self._connections:
            return

        async with self._lock:
            live = list(self._connections)

        dead: list[WebSocket] = []
        for ws in live:
            try:
                await ws.send_json(data)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    try:
                        self._connections.remove(ws)
                    except ValueError:
                        pass


# Singleton used across the app
manager = ConnectionManager()
