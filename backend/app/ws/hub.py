"""WebSocket hub: keeps connected dashboard clients and broadcasts live messages.

Message format: ``{"type": "reading" | "kit_status" | "prediction" | "alert", "data": {...}}``.
The ``/ws/live`` endpoint (with auth) is added in Phase 5.
"""

import json
import logging
from datetime import datetime

from fastapi import WebSocket

log = logging.getLogger(__name__)


def _json_default(value):
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    raise TypeError(f"Cannot serialise {type(value).__name__}")


def encode_message(message_type: str, data: dict) -> str:
    return json.dumps({"type": message_type, "data": data}, default=_json_default)


class WebSocketHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()

    @property
    def client_count(self) -> int:
        return len(self._clients)

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._clients.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._clients.discard(websocket)

    async def broadcast(self, message_type: str, data: dict) -> None:
        if not self._clients:
            return
        text = encode_message(message_type, data)
        for websocket in list(self._clients):
            try:
                await websocket.send_text(text)
            except Exception:
                log.info("Dropping WebSocket client that failed to receive")
                self._clients.discard(websocket)
