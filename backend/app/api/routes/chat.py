"""Chat endpoints for AI agent interaction."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.api.deps import get_current_user
from app.models.database.user import User
from app.agent.orchestrator import process_chat_query, AgentResponse

logger = logging.getLogger(__name__)

router = APIRouter()


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""

    session_id: str = Field(
        ...,
        description="Session ID from Phase 2 (required for drawing context)",
    )
    message: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="User's question or message",
    )
    conversation_id: Optional[str] = Field(
        None,
        description="Optional conversation ID for multi-turn conversations",
    )


class ClarificationOption(BaseModel):
    """Option for a clarification question."""

    label: str
    value: str
    description: Optional[str] = None


class ClarificationQuestion(BaseModel):
    """A pending clarification question."""

    id: str
    question: str
    why_needed: str
    options: Optional[list[ClarificationOption]] = None


class CalculationSummary(BaseModel):
    """Summary of a calculation result."""

    calculation_type: str
    result: float
    unit: str
    limit: Optional[float] = None
    compliant: Optional[bool] = None
    margin: Optional[float] = None


class ChatResponse(BaseModel):
    """Response from chat endpoint."""

    answer: str = Field(..., description="The AI's response")
    conversation_id: str = Field(..., description="ID for continuing conversation")
    query_type: str = Field(..., description="Classification of the query")
    confidence: str = Field(..., description="Confidence level of the answer")

    awaiting_clarification: bool = Field(
        default=False,
        description="Whether the agent is waiting for user clarification",
    )
    clarification_questions: Optional[list[ClarificationQuestion]] = Field(
        None,
        description="Questions waiting for user response",
    )

    sources_used: list[str] = Field(
        default_factory=list,
        description="Section references used in the answer",
    )
    calculations: list[CalculationSummary] = Field(
        default_factory=list,
        description="Calculation results if any were performed",
    )

    suggested_followups: list[str] = Field(
        default_factory=list,
        description="Suggested follow-up questions",
    )

    errors: list[str] = Field(
        default_factory=list,
        description="Any errors encountered during processing",
    )


def _convert_response(
    response: AgentResponse,
    conversation_id: str,
) -> ChatResponse:
    """Convert internal AgentResponse to API ChatResponse."""
    calculations = []
    for calc in response.calculations:
        calculations.append(CalculationSummary(
            calculation_type=calc.get("calculation_type", "unknown"),
            result=calc.get("result", 0),
            unit=calc.get("unit", ""),
            limit=calc.get("limit"),
            compliant=calc.get("compliant"),
            margin=calc.get("margin"),
        ))

    return ChatResponse(
        answer=response.answer,
        conversation_id=conversation_id,
        query_type=response.query_type,
        confidence=response.confidence,
        awaiting_clarification=response.awaiting_clarification,
        clarification_questions=None,
        sources_used=response.sources_used,
        calculations=calculations,
        suggested_followups=response.suggested_followups,
        errors=response.errors,
    )


@router.post(
    "",
    response_model=ChatResponse,
    summary="Send a chat message",
    description=(
        "Send a question about UK permitted development regulations. "
        "The AI will retrieve relevant rules, analyze your drawing context (if uploaded), "
        "and provide a grounded answer with appropriate caveats."
    ),
)
async def chat(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Process a chat message through the AI agent.

    The agent will:
    1. Classify the query type (general, legal_search, compliance_check, calculation)
    2. Load drawing context from the session if available
    3. Retrieve relevant regulations from the knowledge base
    4. Analyze for assumptions and missing information
    5. Either ask for clarification or synthesize an answer
    6. Format the response with caveats and confidence indicators

    Args:
        request: Chat request with session_id and message
        current_user: Authenticated user from JWT

    Returns:
        ChatResponse with the AI's answer and metadata
    """
    logger.info(
        f"Chat request from user {current_user.id}: "
        f"session={request.session_id}, message_len={len(request.message)}"
    )

    try:
        response = await process_chat_query(
            session_id=request.session_id,
            query=request.message,
            conversation_id=request.conversation_id,
        )
    except Exception as e:
        logger.error(f"Chat processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process your question. Please try again.",
        )

    conversation_id = request.conversation_id or request.session_id

    return _convert_response(response, conversation_id)


@router.post(
    "/clarify",
    response_model=ChatResponse,
    summary="Respond to clarification",
    description="Send a response to a clarification question from the AI.",
)
async def respond_to_clarification(
    request: ChatRequest,
    current_user: User = Depends(get_current_user),
) -> ChatResponse:
    """
    Respond to a clarification question.

    When the agent asks for clarification (awaiting_clarification=true),
    use this endpoint to provide the answer. The agent will then
    continue processing with the additional information.

    Args:
        request: Chat request with the clarification response
        current_user: Authenticated user

    Returns:
        ChatResponse with either more questions or the final answer
    """
    if not request.conversation_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="conversation_id is required for clarification responses",
        )

    logger.info(
        f"Clarification response from user {current_user.id}: "
        f"conversation={request.conversation_id}"
    )

    try:
        response = await process_chat_query(
            session_id=request.session_id,
            query=request.message,
            conversation_id=request.conversation_id,
        )
    except Exception as e:
        logger.error(f"Clarification processing failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to process your response. Please try again.",
        )

    return _convert_response(response, request.conversation_id)


class ConversationHistoryResponse(BaseModel):
    """Response with conversation history."""

    conversation_id: str
    turns: list[dict[str, Any]]
    pending_clarification: bool


@router.get(
    "/conversation/{conversation_id}",
    response_model=ConversationHistoryResponse,
    summary="Get conversation history",
    description="Retrieve the history of a conversation.",
)
async def get_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> ConversationHistoryResponse:
    """
    Get conversation history.

    Args:
        conversation_id: The conversation ID to retrieve
        current_user: Authenticated user

    Returns:
        Conversation history with all turns
    """
    from app.agent.orchestrator import get_orchestrator

    orchestrator = await get_orchestrator()
    conversation = orchestrator.get_conversation(conversation_id)

    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )

    if conversation.session_id.split("_")[0] != str(current_user.id):
        pass

    turns = [
        {
            "role": turn.role,
            "content": turn.content,
            "timestamp": turn.timestamp.isoformat(),
            "metadata": turn.metadata,
        }
        for turn in conversation.turns
    ]

    return ConversationHistoryResponse(
        conversation_id=conversation_id,
        turns=turns,
        pending_clarification=bool(conversation.pending_questions),
    )


@router.delete(
    "/conversation/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Clear conversation",
    description="Clear a conversation from memory.",
)
async def clear_conversation(
    conversation_id: str,
    current_user: User = Depends(get_current_user),
) -> None:
    """
    Clear a conversation from memory.

    Args:
        conversation_id: The conversation ID to clear
        current_user: Authenticated user
    """
    from app.agent.orchestrator import get_orchestrator

    orchestrator = await get_orchestrator()
    deleted = orchestrator.clear_conversation(conversation_id)

    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conversation not found",
        )
