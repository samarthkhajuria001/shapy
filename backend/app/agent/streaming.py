"""Streaming orchestrator for WebSocket-based agent execution."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, AsyncIterator, Optional

from openai import AsyncOpenAI
from redis.asyncio import Redis

from app.config import get_settings
from app.agent.state import (
    AgentState,
    ConversationTurn,
    DrawingContext,
    create_initial_state,
)
from app.agent.graph import get_agent_graph
from app.agent.nodes.clarifier import parse_clarification_response
from app.agent.orchestrator import AgentOrchestrator, ConversationContext

logger = logging.getLogger(__name__)


class StreamEventType(str, Enum):
    """Types of events emitted during streaming."""

    NODE_START = "node_start"
    NODE_END = "node_end"
    CLARIFICATION_REQUEST = "clarification_request"
    CALCULATION_RESULT = "calculation_result"
    REASONING_PROGRESS = "reasoning_progress"
    TOKEN = "token"
    RESPONSE_COMPLETE = "response_complete"
    ERROR = "error"


@dataclass
class StreamEvent:
    """An event emitted during streaming execution."""

    event_type: StreamEventType
    node: Optional[str] = None
    data: Optional[dict[str, Any]] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)


NODE_DESCRIPTIONS = {
    "classifier": "Analyzing your question...",
    "context_loader": "Loading drawing context...",
    "retriever": "Searching for relevant regulations...",
    "assumption_analyzer": "Checking for missing information...",
    "clarification_router": "Determining next steps...",
    "clarifier": "Preparing clarification questions...",
    "calculator": "Performing geometric calculations...",
    "validator": "Validating calculation results...",
    "reasoner": "Synthesizing final answer...",
    "response_formatter": "Formatting response...",
}


class StreamingOrchestrator(AgentOrchestrator):
    """
    Extended orchestrator with streaming support.

    Yields StreamEvent objects during graph execution for real-time updates.
    """

    async def process_query_streaming(
        self,
        session_id: str,
        query: str,
        conversation_id: Optional[str] = None,
    ) -> AsyncIterator[StreamEvent]:
        """
        Process a user query with streaming events.

        Yields StreamEvent objects for each significant state change.

        Args:
            session_id: User's session ID
            query: The user's question
            conversation_id: Optional ID for continuing a conversation

        Yields:
            StreamEvent objects during processing
        """
        if self._graph is None:
            await self.initialize()

        conversation = None
        if conversation_id and conversation_id in self._conversations:
            conversation = self._conversations[conversation_id]

        drawing_ctx = None
        history = []

        if conversation:
            drawing_ctx_dict = conversation.drawing_context
            if drawing_ctx_dict:
                drawing_ctx = DrawingContext.model_validate(drawing_ctx_dict)
            history = conversation.turns

            if conversation.pending_questions:
                async for event in self._handle_clarification_response_streaming(
                    conversation=conversation,
                    response=query,
                ):
                    yield event
                return

        initial_state = create_initial_state(
            session_id=session_id,
            user_query=query,
            conversation_id=conversation_id,
            drawing_context=drawing_ctx,
            conversation_history=history,
        )

        config = {
            "configurable": {
                "openai_client": self._openai_client,
                "redis_client": self._redis_client,
            }
        }

        step_index = 0
        final_state = None

        try:
            async for chunk in self._graph.astream(initial_state, config, stream_mode="values"):
                step_index += 1
                final_state = chunk

                node_name = self._detect_current_node(chunk, step_index)

                if node_name:
                    yield StreamEvent(
                        event_type=StreamEventType.NODE_START,
                        node=node_name,
                        data={
                            "step_index": step_index,
                            "message": NODE_DESCRIPTIONS.get(node_name, f"Processing {node_name}..."),
                        },
                    )

                if chunk.get("awaiting_clarification"):
                    questions = chunk.get("clarification_questions", [])
                    for q in questions:
                        yield StreamEvent(
                            event_type=StreamEventType.CLARIFICATION_REQUEST,
                            node="clarifier",
                            data=q,
                        )

                calc_results = chunk.get("calculation_results", [])
                if calc_results:
                    for calc in calc_results:
                        yield StreamEvent(
                            event_type=StreamEventType.CALCULATION_RESULT,
                            node="calculator",
                            data=calc,
                        )

        except Exception as e:
            logger.error(f"Streaming graph execution failed: {e}")
            yield StreamEvent(
                event_type=StreamEventType.ERROR,
                data={
                    "code": "AGENT_ERROR",
                    "message": str(e),
                    "recoverable": True,
                },
            )
            return

        if final_state:
            conv_id = final_state.get("conversation_id", conversation_id or session_id)
            self._update_conversation(
                session_id=session_id,
                conversation_id=conv_id,
                query=query,
                result=final_state,
            )

            message_id = str(uuid.uuid4())
            yield StreamEvent(
                event_type=StreamEventType.RESPONSE_COMPLETE,
                node="response_formatter",
                data=self._build_complete_response(final_state, message_id),
            )

    async def _handle_clarification_response_streaming(
        self,
        conversation: ConversationContext,
        response: str,
    ) -> AsyncIterator[StreamEvent]:
        """Handle clarification response with streaming."""
        questions = conversation.pending_questions

        yield StreamEvent(
            event_type=StreamEventType.NODE_START,
            node="clarification_handler",
            data={
                "step_index": 0,
                "message": "Processing your clarification response...",
            },
        )

        parsed_updates = parse_clarification_response(response, questions)

        if parsed_updates and conversation.drawing_context:
            for field, value in parsed_updates.items():
                conversation.drawing_context[field] = value

            if self._redis_client:
                from app.agent.nodes.context_loader import update_context_from_clarification
                state: AgentState = {
                    "session_id": conversation.session_id,
                    "drawing_context": conversation.drawing_context,
                    "reasoning_chain": [],
                }
                for field, value in parsed_updates.items():
                    await update_context_from_clarification(
                        state, field, value, self._redis_client
                    )

        unanswered = [q for q in questions if not q.get("answered", False)]
        conversation.pending_questions = unanswered

        if unanswered:
            for q in unanswered:
                yield StreamEvent(
                    event_type=StreamEventType.CLARIFICATION_REQUEST,
                    node="clarifier",
                    data=q,
                )
            return

        original_query = ""
        for turn in reversed(conversation.turns):
            if turn.role == "user":
                original_query = turn.content
                break

        async for event in self.process_query_streaming(
            session_id=conversation.session_id,
            query=original_query,
            conversation_id=conversation.conversation_id,
        ):
            yield event

    def _detect_current_node(self, state: AgentState, step_index: int) -> Optional[str]:
        """Detect which node just completed based on state changes."""
        if step_index == 1:
            return "classifier"

        query_type = state.get("query_type")
        has_context = state.get("drawing_context") is not None
        has_rules = bool(state.get("retrieved_rules"))
        has_assumptions = state.get("assumptions") is not None
        awaiting = state.get("awaiting_clarification", False)
        has_calcs = bool(state.get("calculation_results"))
        has_answer = bool(state.get("final_answer"))

        if has_context and not has_rules and step_index <= 3:
            return "context_loader"
        elif has_rules and not has_assumptions:
            return "retriever"
        elif has_assumptions is not None and not awaiting and not has_calcs and not has_answer:
            return "assumption_analyzer"
        elif awaiting:
            return "clarifier"
        elif has_calcs and not has_answer:
            return "calculator"
        elif has_answer and state.get("formatted", False):
            return "response_formatter"
        elif has_answer:
            return "reasoner"

        return None

    def _build_complete_response(
        self,
        state: AgentState,
        message_id: str,
    ) -> dict[str, Any]:
        """Build complete response payload from final state."""
        sources = []
        for rule in state.get("retrieved_rules", []):
            section = rule.get("section")
            page = rule.get("page")
            relevance = rule.get("relevance", 0.5)
            if section:
                sources.append({
                    "section": section,
                    "page": page,
                    "relevance": relevance,
                })

        calculations = []
        for calc in state.get("calculation_results", []):
            calculations.append({
                "calculation_type": calc.get("calculation_type", "unknown"),
                "result": calc.get("result", 0),
                "unit": calc.get("unit", ""),
                "limit": calc.get("limit"),
                "compliant": calc.get("compliant"),
                "margin": calc.get("margin"),
                "description": calc.get("description", ""),
            })

        assumptions = []
        for assumption in state.get("assumptions", []):
            assumptions.append({
                "field": assumption.get("field", ""),
                "value": assumption.get("value"),
                "confidence": assumption.get("confidence", "medium"),
            })

        return {
            "message_id": message_id,
            "final_answer": state.get("final_answer", ""),
            "confidence": state.get("confidence", "medium"),
            "query_type": state.get("query_type", "unknown"),
            "sources": sources,
            "calculations": calculations,
            "assumptions": assumptions,
            "suggested_followups": state.get("suggested_followups", []),
            "awaiting_clarification": state.get("awaiting_clarification", False),
        }


_streaming_orchestrator: Optional[StreamingOrchestrator] = None


async def get_streaming_orchestrator() -> StreamingOrchestrator:
    """Get or create the singleton streaming orchestrator."""
    global _streaming_orchestrator

    if _streaming_orchestrator is None:
        _streaming_orchestrator = StreamingOrchestrator()
        await _streaming_orchestrator.initialize()

    return _streaming_orchestrator
