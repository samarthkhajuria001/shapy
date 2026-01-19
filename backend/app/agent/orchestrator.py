"""Agent orchestrator for managing graph execution."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

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
from app.agent.nodes.context_loader import context_loader_node
from app.agent.nodes.clarifier import parse_clarification_response

logger = logging.getLogger(__name__)


@dataclass
class AgentResponse:
    """Response from agent processing."""

    answer: str
    query_type: str
    confidence: str
    awaiting_clarification: bool
    sources_used: list[str]
    calculations: list[dict]
    assumptions: list[dict]
    caveats: list[str]
    suggested_followups: list[str]
    reasoning_steps: list[str]
    errors: list[str]


@dataclass
class ConversationContext:
    """Stored context for multi-turn conversations."""

    session_id: str
    conversation_id: str
    turns: list[ConversationTurn]
    pending_questions: list[dict]
    drawing_context: Optional[dict]


class AgentOrchestrator:
    """
    Orchestrate agent graph execution with dependency injection.

    Provides:
    - Single query processing
    - Multi-turn conversation management
    - Clarification response handling
    - Session state persistence
    """

    def __init__(
        self,
        openai_client: Optional[AsyncOpenAI] = None,
        redis_client: Optional[Redis] = None,
    ):
        self._openai_client = openai_client
        self._redis_client = redis_client
        self._graph = None
        self._conversations: dict[str, ConversationContext] = {}

    async def initialize(self) -> None:
        """Initialize the orchestrator with required dependencies."""
        settings = get_settings()

        if self._openai_client is None and settings.openai_api_key:
            self._openai_client = AsyncOpenAI(api_key=settings.openai_api_key)

        if self._redis_client is None:
            from app.infrastructure.redis import get_redis
            try:
                self._redis_client = get_redis()
            except RuntimeError:
                logger.warning("Redis not available, running without persistence")

        self._graph = get_agent_graph(use_checkpointer=False)
        logger.info("AgentOrchestrator initialized")

    async def process_query(
        self,
        session_id: str,
        query: str,
        conversation_id: Optional[str] = None,
    ) -> AgentResponse:
        """
        Process a user query through the agent graph.

        Args:
            session_id: User's session ID
            query: The user's question
            conversation_id: Optional ID for continuing a conversation

        Returns:
            AgentResponse with the answer and metadata
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
                return await self._handle_clarification_response(
                    conversation=conversation,
                    response=query,
                )

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

        try:
            result = await self._graph.ainvoke(initial_state, config)
        except Exception as e:
            logger.error(f"Graph execution failed: {e}")
            return AgentResponse(
                answer="I encountered an error processing your question. Please try again.",
                query_type="error",
                confidence="low",
                awaiting_clarification=False,
                sources_used=[],
                calculations=[],
                assumptions=[],
                caveats=[],
                suggested_followups=[],
                reasoning_steps=[],
                errors=[str(e)],
            )

        response = self._build_response(result)

        conv_id = result.get("conversation_id", conversation_id or session_id)
        self._update_conversation(
            session_id=session_id,
            conversation_id=conv_id,
            query=query,
            result=result,
        )

        return response

    async def _handle_clarification_response(
        self,
        conversation: ConversationContext,
        response: str,
    ) -> AgentResponse:
        """Handle a user's response to clarification questions."""
        questions = conversation.pending_questions

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
            from app.agent.nodes.clarifier import clarifier_node
            clarify_state: AgentState = {
                "session_id": conversation.session_id,
                "user_query": conversation.turns[-1].content if conversation.turns else "",
                "clarification_questions": unanswered,
                "reasoning_chain": [],
            }
            result = await clarifier_node(clarify_state, self._openai_client)
            return AgentResponse(
                answer=result.get("final_answer", ""),
                query_type="clarification",
                confidence="medium",
                awaiting_clarification=True,
                sources_used=[],
                calculations=[],
                assumptions=[],
                caveats=[],
                suggested_followups=[],
                reasoning_steps=result.get("reasoning_chain", []),
                errors=[],
            )

        original_query = ""
        for turn in reversed(conversation.turns):
            if turn.role == "user":
                original_query = turn.content
                break

        return await self.process_query(
            session_id=conversation.session_id,
            query=original_query,
            conversation_id=conversation.conversation_id,
        )

    def _build_response(self, result: AgentState) -> AgentResponse:
        """Build AgentResponse from graph result."""
        sources = []
        for rule in result.get("retrieved_rules", []):
            section = rule.get("section")
            if section:
                sources.append(section)

        return AgentResponse(
            answer=result.get("final_answer", ""),
            query_type=result.get("query_type", "unknown"),
            confidence=result.get("confidence", "medium"),
            awaiting_clarification=result.get("awaiting_clarification", False),
            sources_used=sources,
            calculations=result.get("calculation_results", []),
            assumptions=result.get("assumptions", []),
            caveats=result.get("caveats", []),
            suggested_followups=result.get("suggested_followups", []),
            reasoning_steps=result.get("reasoning_chain", []),
            errors=result.get("errors", []),
        )

    def _update_conversation(
        self,
        session_id: str,
        conversation_id: str,
        query: str,
        result: AgentState,
    ) -> None:
        """Update conversation state after processing."""
        now = datetime.now(timezone.utc)

        if conversation_id not in self._conversations:
            self._conversations[conversation_id] = ConversationContext(
                session_id=session_id,
                conversation_id=conversation_id,
                turns=[],
                pending_questions=[],
                drawing_context=result.get("drawing_context"),
            )

        conv = self._conversations[conversation_id]

        conv.turns.append(ConversationTurn(
            role="user",
            content=query,
            timestamp=now,
        ))

        answer = result.get("final_answer", "")
        if answer:
            conv.turns.append(ConversationTurn(
                role="assistant",
                content=answer,
                timestamp=now,
                metadata={
                    "query_type": result.get("query_type"),
                    "confidence": result.get("confidence"),
                    "awaiting_clarification": result.get("awaiting_clarification", False),
                },
            ))

        if result.get("awaiting_clarification"):
            conv.pending_questions = result.get("clarification_questions", [])
        else:
            conv.pending_questions = []

        if result.get("drawing_context"):
            conv.drawing_context = result.get("drawing_context")

    def get_conversation(self, conversation_id: str) -> Optional[ConversationContext]:
        """Get conversation context by ID."""
        return self._conversations.get(conversation_id)

    def clear_conversation(self, conversation_id: str) -> bool:
        """Clear a conversation from memory."""
        if conversation_id in self._conversations:
            del self._conversations[conversation_id]
            return True
        return False


_orchestrator: Optional[AgentOrchestrator] = None


async def get_orchestrator() -> AgentOrchestrator:
    """Get or create the singleton orchestrator."""
    global _orchestrator

    if _orchestrator is None:
        _orchestrator = AgentOrchestrator()
        await _orchestrator.initialize()

    return _orchestrator


async def process_chat_query(
    session_id: str,
    query: str,
    conversation_id: Optional[str] = None,
) -> AgentResponse:
    """
    Convenience function for processing a chat query.

    Args:
        session_id: User's session ID
        query: The question to process
        conversation_id: Optional conversation ID for multi-turn

    Returns:
        AgentResponse with the answer
    """
    orchestrator = await get_orchestrator()
    return await orchestrator.process_query(
        session_id=session_id,
        query=query,
        conversation_id=conversation_id,
    )
