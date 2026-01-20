"""WebSocket chat endpoint."""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.api.ws.manager import get_connection_manager
from app.api.ws.schemas import (
    ClientMessage,
    ClientMessageType,
    ServerMessage,
)
from app.config import get_settings
from app.core.security import decode_token
from app.infrastructure.redis import get_redis
from app.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)

router = APIRouter()


async def validate_ws_connection(
    token: str,
    session_id: str,
) -> tuple[Optional[str], Optional[str]]:
    """
    Validate JWT token and session ownership for WebSocket connection.

    Returns (user_id, error_message). If error_message is not None, connection should be rejected.
    """
    if not token:
        return None, "Missing authentication token"

    payload = decode_token(token)
    if not payload:
        return None, "Invalid token"

    if payload.get("type") != "access":
        return None, "Invalid token type"

    user_id = payload.get("sub")
    if not user_id:
        return None, "Invalid token payload"

    try:
        redis = get_redis()
        settings = get_settings()
        session_repo = SessionRepository(redis, settings.session_ttl_hours * 3600)
        meta = await session_repo.get_meta(session_id)

        if meta is None:
            return None, "Session not found"

        if meta.get("user_id") != user_id:
            return None, "Access denied to session"

    except RuntimeError:
        return None, "Service unavailable"

    return user_id, None


async def get_session_context_info(session_id: str) -> tuple[bool, int]:
    """Get context information for a session."""
    try:
        redis = get_redis()
        settings = get_settings()
        session_repo = SessionRepository(redis, settings.session_ttl_hours * 3600)

        context = await session_repo.get_context(session_id)
        if context is None:
            return False, 0

        metadata = context.get("metadata", {})
        version = metadata.get("context_version", 0)
        return True, version

    except Exception as e:
        logger.warning("Failed to get session context info: %s", str(e))
        return False, 0


@router.websocket("/chat/{session_id}")
async def websocket_chat(
    websocket: WebSocket,
    session_id: str,
    token: str = Query(default=None),
):
    """
    WebSocket endpoint for real-time chat with the AI agent.

    Authentication is done via JWT token passed as query parameter.
    The connection is tied to a specific session for drawing context access.

    Protocol:
    - Client sends: {type: "query" | "clarification_response" | "cancel" | "ping", payload: {...}}
    - Server sends: {type: "connected" | "reasoning_step" | "token" | ... | "error", payload: {...}}
    """
    user_id, error = await validate_ws_connection(token, session_id)

    if error:
        await websocket.close(code=4001, reason=error)
        return

    manager = get_connection_manager()
    connection_id = await manager.connect(websocket, session_id, user_id)

    try:
        has_context, context_version = await get_session_context_info(session_id)

        connected_msg = ServerMessage.connected(
            session_id=session_id,
            has_context=has_context,
            context_version=context_version,
        )
        await manager.send_message(connection_id, connected_msg.model_dump())

        while True:
            try:
                data = await websocket.receive_json()
                await handle_client_message(
                    connection_id=connection_id,
                    session_id=session_id,
                    user_id=user_id,
                    data=data,
                    manager=manager,
                )
            except ValueError as e:
                error_msg = ServerMessage.error(
                    code="INVALID_MESSAGE",
                    message=f"Invalid message format: {str(e)}",
                    recoverable=True,
                )
                await manager.send_message(connection_id, error_msg.model_dump())

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: connection_id=%s", connection_id)
    except Exception as e:
        logger.exception("WebSocket error: %s", str(e))
        try:
            error_msg = ServerMessage.error(
                code="INTERNAL_ERROR",
                message="An unexpected error occurred",
                recoverable=False,
            )
            await manager.send_message(connection_id, error_msg.model_dump())
        except Exception:
            pass
    finally:
        await manager.disconnect(connection_id)


async def handle_client_message(
    connection_id: str,
    session_id: str,
    user_id: str,
    data: dict,
    manager,
) -> None:
    """Process a client message and route to appropriate handler."""
    try:
        message = ClientMessage(**data)
    except Exception as e:
        error_msg = ServerMessage.error(
            code="INVALID_MESSAGE",
            message=f"Failed to parse message: {str(e)}",
            recoverable=True,
        )
        await manager.send_message(connection_id, error_msg.model_dump())
        return

    if message.type == ClientMessageType.PING:
        await manager.update_ping(connection_id)
        pong_msg = ServerMessage.pong()
        await manager.send_message(connection_id, pong_msg.model_dump())
        return

    if message.type == ClientMessageType.QUERY:
        await handle_query(
            connection_id=connection_id,
            session_id=session_id,
            user_id=user_id,
            payload=message.payload,
            manager=manager,
        )
        return

    if message.type == ClientMessageType.CLARIFICATION_RESPONSE:
        await handle_clarification_response(
            connection_id=connection_id,
            session_id=session_id,
            user_id=user_id,
            payload=message.payload,
            manager=manager,
        )
        return

    if message.type == ClientMessageType.CANCEL:
        await handle_cancel(
            connection_id=connection_id,
            session_id=session_id,
            manager=manager,
        )
        return

    error_msg = ServerMessage.error(
        code="UNKNOWN_MESSAGE_TYPE",
        message=f"Unknown message type: {message.type}",
        recoverable=True,
    )
    await manager.send_message(connection_id, error_msg.model_dump())


async def handle_query(
    connection_id: str,
    session_id: str,
    user_id: str,
    payload: Optional[dict],
    manager,
) -> None:
    """Handle a user query message."""
    if not payload or "content" not in payload:
        error_msg = ServerMessage.error(
            code="INVALID_PAYLOAD",
            message="Query payload must include 'content' field",
            recoverable=True,
        )
        await manager.send_message(connection_id, error_msg.model_dump())
        return

    content = payload.get("content", "").strip()
    if not content:
        error_msg = ServerMessage.error(
            code="EMPTY_QUERY",
            message="Query content cannot be empty",
            recoverable=True,
        )
        await manager.send_message(connection_id, error_msg.model_dump())
        return

    logger.info(
        "Query received: connection_id=%s session_id=%s len=%d",
        connection_id,
        session_id,
        len(content),
    )

    from app.agent.streaming import get_streaming_orchestrator, StreamEventType
    from app.api.ws.schemas import (
        ClarificationRequestPayload,
        CalculationPayload,
        ResponseCompletePayload,
        SourceCitation,
        Assumption,
    )

    try:
        orchestrator = await get_streaming_orchestrator()

        async for event in orchestrator.process_query_streaming(
            session_id=session_id,
            query=content,
            conversation_id=session_id,
        ):
            if event.event_type == StreamEventType.NODE_START:
                step_msg = ServerMessage.reasoning_step(
                    step_index=event.data.get("step_index", 0),
                    node=event.node or "unknown",
                    status="processing",
                    message=event.data.get("message", "Processing..."),
                )
                await manager.send_message(connection_id, step_msg.model_dump())

            elif event.event_type == StreamEventType.NODE_END:
                step_msg = ServerMessage.reasoning_step(
                    step_index=event.data.get("step_index", 0),
                    node=event.node or "unknown",
                    status="completed",
                    message=event.data.get("message", "Completed"),
                )
                await manager.send_message(connection_id, step_msg.model_dump())

            elif event.event_type == StreamEventType.CLARIFICATION_REQUEST:
                clarify_payload = ClarificationRequestPayload(
                    id=event.data.get("id", ""),
                    question=event.data.get("question", ""),
                    why_needed=event.data.get("why_needed", ""),
                    field_name=event.data.get("field_name", ""),
                    options=event.data.get("options"),
                    priority=event.data.get("priority", 1),
                    affects_rules=event.data.get("affects_rules", []),
                )
                clarify_msg = ServerMessage.clarification_request(clarify_payload)
                await manager.send_message(connection_id, clarify_msg.model_dump())

            elif event.event_type == StreamEventType.CALCULATION_RESULT:
                calc_payload = CalculationPayload(
                    calculation_type=event.data.get("calculation_type", ""),
                    result=event.data.get("result", 0),
                    unit=event.data.get("unit", ""),
                    limit=event.data.get("limit"),
                    compliant=event.data.get("compliant"),
                    margin=event.data.get("margin"),
                    description=event.data.get("description", ""),
                )
                calc_msg = ServerMessage.calculation(calc_payload)
                await manager.send_message(connection_id, calc_msg.model_dump())

            elif event.event_type == StreamEventType.RESPONSE_COMPLETE:
                data = event.data or {}

                sources = [
                    SourceCitation(
                        section=s.get("section", ""),
                        page=s.get("page"),
                        relevance=s.get("relevance", 0.5),
                    )
                    for s in data.get("sources", [])
                ]

                calculations = [
                    CalculationPayload(
                        calculation_type=c.get("calculation_type", ""),
                        result=c.get("result", 0),
                        unit=c.get("unit", ""),
                        limit=c.get("limit"),
                        compliant=c.get("compliant"),
                        margin=c.get("margin"),
                        description=c.get("description", ""),
                    )
                    for c in data.get("calculations", [])
                ]

                assumptions = [
                    Assumption(
                        field=a.get("field", ""),
                        value=a.get("value"),
                        confidence=a.get("confidence", "medium"),
                    )
                    for a in data.get("assumptions", [])
                ]

                complete_payload = ResponseCompletePayload(
                    message_id=data.get("message_id", ""),
                    final_answer=data.get("final_answer", ""),
                    confidence=data.get("confidence", "medium"),
                    query_type=data.get("query_type", "unknown"),
                    sources=sources,
                    calculations=calculations,
                    assumptions=assumptions,
                    suggested_followups=data.get("suggested_followups", []),
                )
                complete_msg = ServerMessage.response_complete(complete_payload)
                await manager.send_message(connection_id, complete_msg.model_dump())

            elif event.event_type == StreamEventType.ERROR:
                error_msg = ServerMessage.error(
                    code=event.data.get("code", "AGENT_ERROR"),
                    message=event.data.get("message", "An error occurred"),
                    recoverable=event.data.get("recoverable", True),
                )
                await manager.send_message(connection_id, error_msg.model_dump())

    except Exception as e:
        logger.exception("Query processing failed: %s", str(e))
        error_msg = ServerMessage.error(
            code="PROCESSING_ERROR",
            message="Failed to process your question. Please try again.",
            recoverable=True,
        )
        await manager.send_message(connection_id, error_msg.model_dump())


async def handle_clarification_response(
    connection_id: str,
    session_id: str,
    user_id: str,
    payload: Optional[dict],
    manager,
) -> None:
    """Handle a clarification response from the user."""
    if not payload:
        error_msg = ServerMessage.error(
            code="INVALID_PAYLOAD",
            message="Clarification response requires payload",
            recoverable=True,
        )
        await manager.send_message(connection_id, error_msg.model_dump())
        return

    question_id = payload.get("question_id")
    value = payload.get("value")

    if not question_id or value is None:
        error_msg = ServerMessage.error(
            code="INVALID_PAYLOAD",
            message="Clarification response requires 'question_id' and 'value'",
            recoverable=True,
        )
        await manager.send_message(connection_id, error_msg.model_dump())
        return

    logger.info(
        "Clarification response: connection_id=%s question_id=%s",
        connection_id,
        question_id,
    )

    text = payload.get("text", value)
    response_text = f"{question_id}:{text}"

    await handle_query(
        connection_id=connection_id,
        session_id=session_id,
        user_id=user_id,
        payload={"content": response_text},
        manager=manager,
    )


async def handle_cancel(
    connection_id: str,
    session_id: str,
    manager,
) -> None:
    """Handle a cancel request from the user."""
    logger.info(
        "Cancel request: connection_id=%s session_id=%s",
        connection_id,
        session_id,
    )

    # Placeholder: Will implement cancellation logic with streaming orchestrator
    pass
