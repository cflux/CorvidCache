import asyncio
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """Broadcast message to all connected clients."""
        if not self.active_connections:
            logger.warning("No active WebSocket connections for broadcast")
            return

        # Make a copy to avoid modification during iteration
        connections = list(self.active_connections)
        disconnected = []

        for connection in connections:
            try:
                await connection.send_json(message)
            except Exception as e:
                logger.error(f"WebSocket send error: {e}")
                disconnected.append(connection)

        for conn in disconnected:
            self.active_connections.discard(conn)

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send message to a specific client."""
        try:
            await websocket.send_json(message)
        except Exception:
            self.active_connections.discard(websocket)


manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Echo back or handle commands if needed
    except WebSocketDisconnect:
        manager.disconnect(websocket)
