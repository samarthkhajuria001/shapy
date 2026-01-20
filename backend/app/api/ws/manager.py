"""WebSocket connection management."""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)


@dataclass
class ActiveConnection:
    """Represents an active WebSocket connection."""

    websocket: WebSocket
    session_id: str
    user_id: str
    connected_at: datetime = field(default_factory=datetime.utcnow)
    last_ping: datetime = field(default_factory=datetime.utcnow)


class ConnectionManager:
    """
    Manages WebSocket connections for chat sessions.

    Tracks connections by session_id and user_id for efficient message routing.
    Supports multiple connections per session (e.g., multi-device access).
    """

    def __init__(self):
        self._connections: dict[str, ActiveConnection] = {}
        self._session_to_connections: dict[str, set[str]] = {}
        self._user_to_connections: dict[str, set[str]] = {}
        self._lock = asyncio.Lock()

    def _generate_connection_id(self, websocket: WebSocket) -> str:
        return f"{id(websocket)}_{datetime.utcnow().timestamp()}"

    async def connect(
        self,
        websocket: WebSocket,
        session_id: str,
        user_id: str,
    ) -> str:
        """
        Accept a WebSocket connection and register it.

        Returns the connection_id for tracking.
        """
        await websocket.accept()
        connection_id = self._generate_connection_id(websocket)

        async with self._lock:
            connection = ActiveConnection(
                websocket=websocket,
                session_id=session_id,
                user_id=user_id,
            )
            self._connections[connection_id] = connection

            if session_id not in self._session_to_connections:
                self._session_to_connections[session_id] = set()
            self._session_to_connections[session_id].add(connection_id)

            if user_id not in self._user_to_connections:
                self._user_to_connections[user_id] = set()
            self._user_to_connections[user_id].add(connection_id)

        logger.info(
            "WebSocket connected: connection_id=%s session_id=%s user_id=%s",
            connection_id,
            session_id,
            user_id,
        )
        return connection_id

    async def disconnect(self, connection_id: str) -> None:
        """Remove a connection from tracking."""
        async with self._lock:
            connection = self._connections.pop(connection_id, None)
            if connection is None:
                return

            session_id = connection.session_id
            user_id = connection.user_id

            if session_id in self._session_to_connections:
                self._session_to_connections[session_id].discard(connection_id)
                if not self._session_to_connections[session_id]:
                    del self._session_to_connections[session_id]

            if user_id in self._user_to_connections:
                self._user_to_connections[user_id].discard(connection_id)
                if not self._user_to_connections[user_id]:
                    del self._user_to_connections[user_id]

        logger.info(
            "WebSocket disconnected: connection_id=%s session_id=%s",
            connection_id,
            session_id,
        )

    async def send_message(
        self,
        connection_id: str,
        message: dict[str, Any],
    ) -> bool:
        """
        Send a JSON message to a specific connection.

        Returns True if sent successfully, False if connection not found or failed.
        """
        connection = self._connections.get(connection_id)
        if connection is None:
            return False

        try:
            await connection.websocket.send_json(message)
            return True
        except WebSocketDisconnect:
            await self.disconnect(connection_id)
            return False
        except Exception as e:
            logger.warning(
                "Failed to send message to connection %s: %s",
                connection_id,
                str(e),
            )
            return False

    async def broadcast_to_session(
        self,
        session_id: str,
        message: dict[str, Any],
        exclude_connection: Optional[str] = None,
    ) -> int:
        """
        Send a message to all connections in a session.

        Returns the number of successful sends.
        """
        connection_ids = self._session_to_connections.get(session_id, set()).copy()
        if exclude_connection:
            connection_ids.discard(exclude_connection)

        success_count = 0
        for conn_id in connection_ids:
            if await self.send_message(conn_id, message):
                success_count += 1

        return success_count

    async def broadcast_to_user(
        self,
        user_id: str,
        message: dict[str, Any],
    ) -> int:
        """
        Send a message to all connections for a user.

        Returns the number of successful sends.
        """
        connection_ids = self._user_to_connections.get(user_id, set()).copy()

        success_count = 0
        for conn_id in connection_ids:
            if await self.send_message(conn_id, message):
                success_count += 1

        return success_count

    def get_session_connection_count(self, session_id: str) -> int:
        """Get the number of active connections for a session."""
        return len(self._session_to_connections.get(session_id, set()))

    def get_user_connection_count(self, user_id: str) -> int:
        """Get the number of active connections for a user."""
        return len(self._user_to_connections.get(user_id, set()))

    def is_session_connected(self, session_id: str) -> bool:
        """Check if a session has any active connections."""
        return session_id in self._session_to_connections

    def get_connection(self, connection_id: str) -> Optional[ActiveConnection]:
        """Get connection info by ID."""
        return self._connections.get(connection_id)

    async def update_ping(self, connection_id: str) -> None:
        """Update the last ping time for a connection."""
        connection = self._connections.get(connection_id)
        if connection:
            connection.last_ping = datetime.utcnow()

    @property
    def total_connections(self) -> int:
        """Get total number of active connections."""
        return len(self._connections)

    @property
    def active_sessions(self) -> int:
        """Get number of sessions with active connections."""
        return len(self._session_to_connections)


_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the singleton ConnectionManager instance."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager
