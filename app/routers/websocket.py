"""
WebSocket router for real-time progress updates.

Provides a WebSocket endpoint that clients connect to for receiving
live download progress updates, status changes, and notifications.
"""

import asyncio
import logging
from typing import Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import json

router = APIRouter()
logger = logging.getLogger(__name__)


class ConnectionManager:
    """
    Manages WebSocket connections for real-time updates.

    Tracks all active client connections and provides methods for
    broadcasting messages to all clients or sending to specific ones.
    """

    def __init__(self):
        self.active_connections: Set[WebSocket] = set()

    async def connect(self, websocket: WebSocket):
        """Accept a new WebSocket connection and add to active set."""
        await websocket.accept()
        self.active_connections.add(websocket)
        logger.info(f"WebSocket connected. Total connections: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        """Remove a WebSocket connection from the active set."""
        self.active_connections.discard(websocket)
        logger.info(f"WebSocket disconnected. Total connections: {len(self.active_connections)}")

    async def broadcast(self, message: dict):
        """
        Broadcast a message to all connected clients.

        Automatically handles disconnected clients by removing them
        from the active connections set.

        Args:
            message: Dictionary to send as JSON to all clients.
        """
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
        """
        Send a message to a specific client.

        Args:
            websocket: Target WebSocket connection.
            message: Dictionary to send as JSON.
        """
        try:
            await websocket.send_json(message)
        except Exception:
            self.active_connections.discard(websocket)


# Global connection manager instance used by other modules
manager = ConnectionManager()


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """
    WebSocket endpoint for real-time updates.

    Clients connect here to receive live updates about:
    - Download progress (percentage, speed, ETA)
    - Status changes (queued -> downloading -> completed)
    - Error notifications
    """
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive, receive any client messages
            data = await websocket.receive_text()
            # Client messages could be used for ping/pong or commands
    except WebSocketDisconnect:
        manager.disconnect(websocket)
