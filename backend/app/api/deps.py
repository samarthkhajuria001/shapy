"""Dependency injection for routes."""

from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, Settings
from app.core.exceptions import InvalidTokenError
from app.core.security import decode_token
from app.infrastructure.database import get_db
from app.infrastructure.redis import get_redis
from app.models.database.user import User
from app.repositories.user_repository import UserRepository
from app.services.session_service import SessionService


async def get_current_user(
    authorization: Annotated[str, Header()],
    db: AsyncSession = Depends(get_db),
) -> User:
    if not authorization.startswith("Bearer "):
        raise InvalidTokenError()

    token = authorization.replace("Bearer ", "")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise InvalidTokenError()

    user_id = payload.get("sub")
    user_repo = UserRepository(db)
    user = await user_repo.get_by_id(user_id)

    if not user:
        raise InvalidTokenError()

    return user


def get_session_service(
    settings: Settings = Depends(get_settings),
) -> SessionService:
    redis = get_redis()
    return SessionService(redis, settings)
