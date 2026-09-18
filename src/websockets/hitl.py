import json
import logging
from typing import Dict, Optional
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from src.auth.jwt_handler import decode_access_token

logger = logging.getLogger(__name__)


class HITLConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.pending_requests: Dict[str, dict] = {}

    async def connect(self, websocket: WebSocket, run_id: str, token: str) -> bool:
        payload = decode_access_token(token)
        if not payload:
            await websocket.close(code=4001, reason="Invalid token")
            return False

        user_id = payload.get("sub")
        if not user_id:
            await websocket.close(code=4001, reason="Invalid token subject")
            return False

        if run_id in self.active_connections:
            old_ws = self.active_connections[run_id]
            try:
                await old_ws.close(code=4009, reason="Replaced by new connection")
            except Exception:
                pass

        await websocket.accept()
        self.active_connections[run_id] = websocket
        logger.info("HITL connected for run %s (user %s)", run_id, user_id)

        if run_id in self.pending_requests:
            try:
                await websocket.send_json(self.pending_requests[run_id])
            except Exception:
                pass

        return True

    def disconnect(self, run_id: str):
        self.active_connections.pop(run_id, None)

    async def send_request(self, run_id: str, message: dict):
        ws = self.active_connections.get(run_id)
        if ws and ws.client_state == WebSocketState.CONNECTED:
            try:
                await ws.send_json(message)
                return True
            except Exception:
                pass

        self.pending_requests[run_id] = message
        return False

    async def receive_response(self, run_id: str, timeout: float = 300.0) -> Optional[dict]:
        ws = self.active_connections.get(run_id)
        if not ws:
            return None

        try:
            data = await asyncio.wait_for(ws.receive_text(), timeout=timeout)
            return json.loads(data)
        except Exception:
            return None


hitl_manager = HITLConnectionManager()

import asyncio


async def websocket_hitl_endpoint(websocket: WebSocket, project_id: str, run_id: str, token: str):
    connected = await hitl_manager.connect(websocket, run_id, token)
    if not connected:
        return

    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                msg_type = message.get("type")

                if msg_type in ("clarification_response", "approval_response"):
                    logger.info("Received %s for run %s", msg_type, run_id)
                else:
                    await websocket.send_json({
                        "type": "error",
                        "payload": {"message": f"Unexpected message type: {msg_type}"},
                    })
            except json.JSONDecodeError:
                await websocket.send_json({
                    "type": "error",
                    "payload": {"message": "Invalid JSON"},
                })
    except WebSocketDisconnect:
        hitl_manager.disconnect(run_id)
        logger.info("HITL disconnected for run %s", run_id)
    except Exception as e:
        hitl_manager.disconnect(run_id)
        logger.error("HITL error for run %s: %s", run_id, e)
