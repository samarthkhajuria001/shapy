"""Redis connection management."""

from typing import Optional

import redis.asyncio as redis

from app.config import get_settings

redis_client: Optional[redis.Redis] = None


async def init_redis():
    global redis_client
    settings = get_settings()
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)


async def close_redis():
    global redis_client
    if redis_client:
        await redis_client.close()


def get_redis() -> redis.Redis:
    if redis_client is None:
        raise RuntimeError("Redis not initialized")
    return redis_client
