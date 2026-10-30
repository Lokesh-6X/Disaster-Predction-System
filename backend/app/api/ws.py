"""Live updates over WebSocket: ``/ws/live?token=<jwt>`` (FR-API-02, design §13.3).

An invalid or expired token closes the socket with code 4401. The server sends
``{"type": "ping"}`` every 30 s of silence so dead clients are noticed.
"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from backend.app.security import decode_token
from backend.app.ws.hub import encode_message

router = APIRouter()

PING_INTERVAL_S = 30
UNAUTHORIZED = 4401


@router.websocket("/ws/live")
async def live(websocket: WebSocket, token: str = "") -> None:
    state = websocket.app.state
    if decode_token(token, state.config.env) is None:
        await websocket.accept()
        await websocket.close(code=UNAUTHORIZED, reason="Not logged in or session expired")
        return
    await state.hub.connect(websocket)
    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=PING_INTERVAL_S)
            except TimeoutError:
                await websocket.send_text(encode_message("ping", {}))
    except WebSocketDisconnect:
        pass
    finally:
        state.hub.disconnect(websocket)
