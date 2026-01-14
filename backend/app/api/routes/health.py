"""Health check endpoints."""

from fastapi import APIRouter, status
from pydantic import BaseModel

from app.infrastructure.database import engine
from app.infrastructure.redis import redis_client

router = APIRouter()


class HealthResponse(BaseModel):
    status: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    redis: str


@router.get("/health", response_model=HealthResponse)
async def health():
    from app.config import get_settings
    settings = get_settings()
    return HealthResponse(status="healthy", version=settings.app_version)


@router.get("/health/ready", response_model=ReadyResponse, status_code=status.HTTP_200_OK)
async def ready():
    db_status = "disconnected"
    redis_status = "disconnected"

    if engine:
        try:
            async with engine.connect() as conn:
                await conn.execute("SELECT 1")
            db_status = "connected"
        except Exception:
            db_status = "error"

    if redis_client:
        try:
            await redis_client.ping()
            redis_status = "connected"
        except Exception:
            redis_status = "error"

    overall = "ready" if db_status == "connected" and redis_status == "connected" else "not_ready"
    return ReadyResponse(status=overall, database=db_status, redis=redis_status)
