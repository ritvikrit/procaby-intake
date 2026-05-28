import logging
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()


class ConnectionManager:
    def __init__(self):
        self._connections: dict[str, list[WebSocket]] = {}

    async def connect(self, ws: WebSocket, procurement_id: str) -> None:
        await ws.accept()
        self._connections.setdefault(procurement_id, []).append(ws)
        logger.info(f"WS connected for {procurement_id}. Total: {len(self._connections[procurement_id])}")

    def disconnect(self, ws: WebSocket, procurement_id: str) -> None:
        conns = self._connections.get(procurement_id, [])
        if ws in conns:
            conns.remove(ws)
        if not conns:
            self._connections.pop(procurement_id, None)
        logger.info(f"WS disconnected for {procurement_id}")

    async def broadcast(self, procurement_id: str, message: dict) -> None:
        conns = list(self._connections.get(procurement_id, []))
        dead = []
        for ws in conns:
            try:
                import json
                await ws.send_text(json.dumps(message))
            except Exception as exc:
                logger.error(f"Error sending WS message: {exc}")
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws, procurement_id)


ws_manager = ConnectionManager()


@router.websocket("/auction/{procurement_id}")
async def auction_feed(ws: WebSocket, procurement_id: str):
    await ws_manager.connect(ws, procurement_id)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(ws, procurement_id)
