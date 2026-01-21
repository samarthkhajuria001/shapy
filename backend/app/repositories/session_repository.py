"""Session repository for Redis operations."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from redis.asyncio import Redis


class SessionRepository:
    """Data access layer for session and context management in Redis."""

    def __init__(self, redis: Redis, ttl_seconds: int):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    def _meta_key(self, session_id: str) -> str:
        return f"session:{session_id}:meta"

    def _context_key(self, session_id: str) -> str:
        return f"session:{session_id}:context"

    def _messages_key(self, session_id: str) -> str:
        return f"session:{session_id}:messages"

    def _user_sessions_key(self, user_id: str) -> str:
        return f"user:{user_id}:sessions"

    async def create(self, user_id: str) -> dict[str, Any]:
        """Create a new session for a user. Returns session metadata."""
        session_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)

        meta = {
            "session_id": session_id,
            "user_id": user_id,
            "created_at": now.isoformat(),
            "updated_at": None,
            "context_version": 0,
        }

        meta_key = self._meta_key(session_id)
        user_key = self._user_sessions_key(user_id)

        pipe = self.redis.pipeline()
        pipe.set(meta_key, json.dumps(meta), ex=self.ttl_seconds)
        pipe.sadd(user_key, session_id)
        await pipe.execute()

        return meta

    async def get_meta(self, session_id: str) -> dict[str, Any] | None:
        """Get session metadata. Returns None if not found or expired."""
        data = await self.redis.get(self._meta_key(session_id))
        if data is None:
            return None
        return json.loads(data)

    async def update_meta(self, session_id: str, **updates: Any) -> bool:
        """Update session metadata fields. Returns False if session not found."""
        meta = await self.get_meta(session_id)
        if meta is None:
            return False

        meta.update(updates)
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        ttl = await self.redis.ttl(self._meta_key(session_id))
        if ttl > 0:
            await self.redis.set(
                self._meta_key(session_id),
                json.dumps(meta),
                ex=ttl,
            )
        return True

    async def get_context(self, session_id: str) -> dict[str, Any] | None:
        """Get drawing context. Returns None if not found."""
        data = await self.redis.get(self._context_key(session_id))
        if data is None:
            return None
        return json.loads(data)

    async def set_context(
        self,
        session_id: str,
        objects: list[dict[str, Any]],
        metadata: dict[str, Any],
    ) -> bool:
        """
        Set drawing context and refresh TTL.
        Returns False if session not found.
        """
        meta = await self.get_meta(session_id)
        if meta is None:
            return False

        context = {
            "objects": objects,
            "metadata": metadata,
        }

        meta["context_version"] = meta.get("context_version", 0) + 1
        meta["updated_at"] = datetime.now(timezone.utc).isoformat()

        meta_key = self._meta_key(session_id)
        context_key = self._context_key(session_id)

        pipe = self.redis.pipeline()
        pipe.set(meta_key, json.dumps(meta), ex=self.ttl_seconds)
        pipe.set(context_key, json.dumps(context), ex=self.ttl_seconds)
        await pipe.execute()

        return True

    async def delete(self, session_id: str, user_id: str) -> bool:
        """Delete session and all related keys. Returns True if deleted."""
        meta_key = self._meta_key(session_id)
        context_key = self._context_key(session_id)
        user_key = self._user_sessions_key(user_id)

        pipe = self.redis.pipeline()
        pipe.delete(meta_key)
        pipe.delete(context_key)
        pipe.srem(user_key, session_id)
        results = await pipe.execute()

        return results[0] > 0

    async def exists(self, session_id: str) -> bool:
        """Check if session exists."""
        return await self.redis.exists(self._meta_key(session_id)) > 0

    async def get_ttl(self, session_id: str) -> int | None:
        """Get remaining TTL in seconds. Returns None if key doesn't exist."""
        ttl = await self.redis.ttl(self._meta_key(session_id))
        if ttl < 0:
            return None
        return ttl

    async def count_user_sessions(self, user_id: str) -> int:
        """Count active sessions for a user (with cleanup of expired)."""
        user_key = self._user_sessions_key(user_id)
        session_ids = await self.redis.smembers(user_key)

        if not session_ids:
            return 0

        valid_count = 0
        expired_ids = []

        for session_id in session_ids:
            if await self.exists(session_id):
                valid_count += 1
            else:
                expired_ids.append(session_id)

        if expired_ids:
            await self.redis.srem(user_key, *expired_ids)

        return valid_count

    async def get_user_sessions(self, user_id: str) -> list[dict[str, Any]]:
        """Get all active sessions for a user (with cleanup of expired)."""
        user_key = self._user_sessions_key(user_id)
        session_ids = await self.redis.smembers(user_key)

        if not session_ids:
            return []

        sessions = []
        expired_ids = []

        for session_id in session_ids:
            meta = await self.get_meta(session_id)
            if meta is not None:
                context = await self.get_context(session_id)
                meta["has_context"] = context is not None
                meta["object_count"] = 0
                if context and "objects" in context:
                    meta["object_count"] = len(context["objects"])
                sessions.append(meta)
            else:
                expired_ids.append(session_id)

        if expired_ids:
            await self.redis.srem(user_key, *expired_ids)

        sessions.sort(key=lambda x: x["created_at"], reverse=True)
        return sessions

    async def get_owner_id(self, session_id: str) -> str | None:
        """Get the user_id who owns this session. Returns None if not found."""
        meta = await self.get_meta(session_id)
        if meta is None:
            return None
        return meta.get("user_id")

    async def add_message(
        self,
        session_id: str,
        role: str,
        content: str,
        message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """
        Add a message to the session's conversation history.
        Returns the message dict or None if session not found.
        """
        if not await self.exists(session_id):
            return None

        now = datetime.now(timezone.utc)
        message = {
            "id": message_id or str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": now.isoformat(),
            **(metadata or {}),
        }

        messages_key = self._messages_key(session_id)
        await self.redis.rpush(messages_key, json.dumps(message))
        await self.redis.expire(messages_key, self.ttl_seconds)

        return message

    async def get_messages(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get all messages for a session.
        Returns empty list if session not found or no messages.
        """
        messages_key = self._messages_key(session_id)

        if limit:
            data = await self.redis.lrange(messages_key, -limit, -1)
        else:
            data = await self.redis.lrange(messages_key, 0, -1)

        messages = []
        for item in data:
            try:
                messages.append(json.loads(item))
            except json.JSONDecodeError:
                continue

        return messages

    async def clear_messages(self, session_id: str) -> bool:
        """Clear all messages for a session. Returns True if cleared."""
        messages_key = self._messages_key(session_id)
        result = await self.redis.delete(messages_key)
        return result > 0
