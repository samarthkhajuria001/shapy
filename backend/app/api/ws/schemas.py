"""WebSocket message schemas."""

from datetime import datetime
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class ClientMessageType(str, Enum):
    """Types of messages the client can send."""

    QUERY = "query"
    CLARIFICATION_RESPONSE = "clarification_response"
    CANCEL = "cancel"
    PING = "ping"


class ServerMessageType(str, Enum):
    """Types of messages the server can send."""

    CONNECTED = "connected"
    REASONING_STEP = "reasoning_step"
    TOKEN = "token"
    TOKENS = "tokens"
    CLARIFICATION_REQUEST = "clarification_request"
    CALCULATION = "calculation"
    CONTEXT_UPDATED = "context_updated"
    RESPONSE_COMPLETE = "response_complete"
    ERROR = "error"
    PONG = "pong"


class QueryPayload(BaseModel):
    """Payload for a user query message."""

    content: str = Field(..., min_length=1, max_length=2000)
    include_reasoning: bool = True


class ClarificationResponsePayload(BaseModel):
    """Payload for responding to a clarification request."""

    question_id: str
    value: str
    text: Optional[str] = None


class ClientMessage(BaseModel):
    """Base model for client -> server messages."""

    type: ClientMessageType
    payload: Optional[dict[str, Any]] = None


class ConnectedPayload(BaseModel):
    """Payload for connection established message."""

    session_id: str
    has_context: bool
    context_version: int


class ReasoningStepPayload(BaseModel):
    """Payload for reasoning step progress updates."""

    step_index: int
    node: str
    status: Literal["processing", "completed", "skipped"]
    message: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class TokenPayload(BaseModel):
    """Payload for a single streamed token."""

    chunk: str
    node: str
    token_index: int


class TokensPayload(BaseModel):
    """Payload for batched streamed tokens."""

    chunks: list[str]
    node: str


class ClarificationOption(BaseModel):
    """An option for a clarification question."""

    label: str
    value: str
    description: Optional[str] = None


class ClarificationRequestPayload(BaseModel):
    """Payload for a clarification request from the agent."""

    id: str
    question: str
    why_needed: str
    field_name: str
    options: Optional[list[ClarificationOption]] = None
    priority: int = 1
    affects_rules: list[str] = Field(default_factory=list)


class VisualizationHint(BaseModel):
    """Hints for drawing visualization."""

    highlight_layers: list[str]
    highlight_color: str = "#22c55e"


class CalculationPayload(BaseModel):
    """Payload for a calculation result."""

    calculation_type: str
    result: float
    unit: str
    limit: Optional[float] = None
    compliant: Optional[bool] = None
    margin: Optional[float] = None
    description: str
    visualization_hint: Optional[VisualizationHint] = None


class InferredData(BaseModel):
    """Data inferred from the drawing context."""

    principal_elevation: Optional[str] = None
    rear_wall_identified: bool = False
    house_type_detected: Optional[str] = None


class ContextUpdatedPayload(BaseModel):
    """Payload for context update notification."""

    source: str
    version: int
    changes: list[str]
    inferred_data: Optional[InferredData] = None


class SourceCitation(BaseModel):
    """A source citation from the knowledge base."""

    section: str
    page: Optional[int] = None
    relevance: float


class Assumption(BaseModel):
    """An assumption made during processing."""

    field: str
    value: Any
    confidence: Literal["high", "medium", "low"]


class ResponseCompletePayload(BaseModel):
    """Payload for a completed response."""

    message_id: str
    final_answer: str
    confidence: Literal["high", "medium", "low"]
    query_type: str
    sources: list[SourceCitation] = Field(default_factory=list)
    calculations: list[CalculationPayload] = Field(default_factory=list)
    assumptions: list[Assumption] = Field(default_factory=list)
    suggested_followups: list[str] = Field(default_factory=list)


class ErrorPayload(BaseModel):
    """Payload for error messages."""

    code: str
    message: str
    recoverable: bool = True


class ServerMessage(BaseModel):
    """Base model for server -> client messages."""

    type: ServerMessageType
    payload: dict[str, Any]

    @classmethod
    def connected(cls, session_id: str, has_context: bool, context_version: int):
        return cls(
            type=ServerMessageType.CONNECTED,
            payload=ConnectedPayload(
                session_id=session_id,
                has_context=has_context,
                context_version=context_version,
            ).model_dump(),
        )

    @classmethod
    def reasoning_step(
        cls,
        step_index: int,
        node: str,
        status: str,
        message: str,
    ):
        return cls(
            type=ServerMessageType.REASONING_STEP,
            payload=ReasoningStepPayload(
                step_index=step_index,
                node=node,
                status=status,
                message=message,
            ).model_dump(mode="json"),
        )

    @classmethod
    def token(cls, chunk: str, node: str, token_index: int):
        return cls(
            type=ServerMessageType.TOKEN,
            payload=TokenPayload(
                chunk=chunk,
                node=node,
                token_index=token_index,
            ).model_dump(),
        )

    @classmethod
    def tokens(cls, chunks: list[str], node: str):
        return cls(
            type=ServerMessageType.TOKENS,
            payload=TokensPayload(
                chunks=chunks,
                node=node,
            ).model_dump(),
        )

    @classmethod
    def clarification_request(cls, payload: ClarificationRequestPayload):
        return cls(
            type=ServerMessageType.CLARIFICATION_REQUEST,
            payload=payload.model_dump(),
        )

    @classmethod
    def calculation(cls, payload: CalculationPayload):
        return cls(
            type=ServerMessageType.CALCULATION,
            payload=payload.model_dump(),
        )

    @classmethod
    def context_updated(cls, payload: ContextUpdatedPayload):
        return cls(
            type=ServerMessageType.CONTEXT_UPDATED,
            payload=payload.model_dump(),
        )

    @classmethod
    def response_complete(cls, payload: ResponseCompletePayload):
        return cls(
            type=ServerMessageType.RESPONSE_COMPLETE,
            payload=payload.model_dump(mode="json"),
        )

    @classmethod
    def error(cls, code: str, message: str, recoverable: bool = True):
        return cls(
            type=ServerMessageType.ERROR,
            payload=ErrorPayload(
                code=code,
                message=message,
                recoverable=recoverable,
            ).model_dump(),
        )

    @classmethod
    def pong(cls):
        return cls(
            type=ServerMessageType.PONG,
            payload={},
        )
