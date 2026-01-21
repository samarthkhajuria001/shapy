"""Session management endpoints."""

from fastapi import APIRouter, Depends, status

from app.api.deps import get_current_user, get_session_service
from app.models.database.user import User
from app.models.schemas.session import (
    ContextGetResponse,
    ContextUpdateRequest,
    ContextUpdateResponse,
    MessagesResponse,
    SessionCreateResponse,
    SessionListResponse,
    SessionStatusResponse,
)
from app.services.session_service import SessionService

router = APIRouter()


@router.post(
    "",
    response_model=SessionCreateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_session(
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> SessionCreateResponse:
    """Create a new session for the current user."""
    return await session_service.create_session(current_user.id)


@router.get("", response_model=SessionListResponse)
async def list_sessions(
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> SessionListResponse:
    """List all sessions for the current user."""
    return await session_service.list_sessions(current_user.id)


@router.get("/{session_id}", response_model=SessionStatusResponse)
async def get_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> SessionStatusResponse:
    """Get session status and metadata."""
    return await session_service.get_session(session_id, current_user.id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> None:
    """Delete a session."""
    await session_service.delete_session(session_id, current_user.id)


@router.put("/{session_id}/context", response_model=ContextUpdateResponse)
async def update_context(
    session_id: str,
    request: ContextUpdateRequest,
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> ContextUpdateResponse:
    """Update drawing context for a session."""
    return await session_service.update_context(
        session_id,
        current_user.id,
        request.objects,
    )


@router.get("/{session_id}/context", response_model=ContextGetResponse)
async def get_context(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> ContextGetResponse:
    """Get drawing context for a session."""
    return await session_service.get_context(session_id, current_user.id)


@router.get("/{session_id}/messages", response_model=MessagesResponse)
async def get_messages(
    session_id: str,
    current_user: User = Depends(get_current_user),
    session_service: SessionService = Depends(get_session_service),
) -> MessagesResponse:
    """Get chat messages for a session."""
    return await session_service.get_messages(session_id, current_user.id)
