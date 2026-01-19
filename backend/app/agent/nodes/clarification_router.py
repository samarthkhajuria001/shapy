"""Clarification router node for deciding whether to ask for user input."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.state import (
    AgentState,
    MissingInfoType,
    QueryType,
    add_reasoning_step,
)

logger = logging.getLogger(__name__)


CRITICAL_MISSING_TYPES = {
    MissingInfoType.DRAWING.value,
    MissingInfoType.ORIGINAL_HOUSE.value,
    MissingInfoType.HOUSE_TYPE.value,
}

IMPORTANT_MISSING_TYPES = {
    MissingInfoType.DESIGNATED_LAND.value,
    MissingInfoType.PRIOR_EXTENSIONS.value,
}


def _get_unanswered_questions(
    questions: list[dict],
    max_priority: int = 2,
) -> list[dict]:
    """Get unanswered clarification questions up to a priority level."""
    return [
        q for q in questions
        if not q.get("answered", False) and q.get("priority", 2) <= max_priority
    ]


def _has_pending_calculations(state: AgentState) -> bool:
    """Check if calculations are needed based on query type and drawing."""
    query_type = state.get("query_type", "")
    drawing_ctx = state.get("drawing_context")

    if query_type not in {QueryType.COMPLIANCE_CHECK.value, QueryType.CALCULATION.value}:
        return False

    if not drawing_ctx or not drawing_ctx.get("has_drawing"):
        return False

    retrieved_rules = state.get("retrieved_rules", [])

    calculation_triggers = [
        "50%", "curtilage", "coverage",
        "2 metres", "boundary",
        "height", "metres",
        "area", "distance",
    ]

    for rule in retrieved_rules:
        text = rule.get("text", "").lower()
        if any(trigger in text for trigger in calculation_triggers):
            return True

    return False


def _determine_pending_calculations(state: AgentState) -> list[str]:
    """Determine what calculations are needed based on rules and query."""
    pending: list[str] = []

    query = state.get("user_query", "").lower()
    retrieved_rules = state.get("retrieved_rules", [])
    drawing_ctx = state.get("drawing_context")

    if not drawing_ctx or not drawing_ctx.get("has_drawing"):
        return pending

    all_text = query + " ".join(r.get("text", "") for r in retrieved_rules).lower()

    if "50%" in all_text or "curtilage" in all_text or "coverage" in all_text:
        pending.append("coverage_percentage")

    if "boundary" in all_text or "2 metre" in all_text or "2m" in all_text:
        pending.append("boundary_distance")

    if "height" in all_text and any(kw in all_text for kw in ["max", "limit", "exceed"]):
        pending.append("height_check")

    if "rear" in all_text and any(kw in all_text for kw in ["extension", "project", "depth"]):
        pending.append("extension_depth")

    return pending


async def clarification_router_node(state: AgentState) -> dict[str, Any]:
    """
    Decide whether to ask for clarification or proceed with processing.

    This node determines the routing path:
    - needs_clarification: Stop and ask user for critical missing info
    - proceed_to_calculator: Have enough info, proceed to calculations
    - skip_calculator: No calculations needed, go directly to reasoner

    Args:
        state: Current agent state with missing_info and clarification_questions

    Returns:
        State updates with awaiting_clarification flag and pending_calculations
    """
    missing_info = set(state.get("missing_info", []))
    questions = state.get("clarification_questions", [])
    query_type = state.get("query_type", "")

    is_compliance = query_type in {
        QueryType.COMPLIANCE_CHECK.value,
        QueryType.CALCULATION.value,
    }

    critical_missing = missing_info & CRITICAL_MISSING_TYPES

    if MissingInfoType.DRAWING.value in critical_missing:
        unanswered = _get_unanswered_questions(questions, max_priority=1)
        return {
            "awaiting_clarification": True,
            "pending_calculations": [],
            "reasoning_chain": add_reasoning_step(
                state,
                "Drawing required but not uploaded, requesting upload",
            ),
        }

    if is_compliance:
        priority_1_questions = [
            q for q in _get_unanswered_questions(questions, max_priority=1)
            if q.get("field_name") != "has_drawing"
        ]

        if priority_1_questions:
            logger.debug(f"Found {len(priority_1_questions)} priority-1 questions")
            return {
                "awaiting_clarification": True,
                "pending_calculations": [],
                "reasoning_chain": add_reasoning_step(
                    state,
                    f"Need clarification: {len(priority_1_questions)} critical questions",
                ),
            }

        priority_2_questions = _get_unanswered_questions(questions, max_priority=2)
        priority_2_non_answered = [
            q for q in priority_2_questions
            if q.get("field_name") != "has_drawing"
        ]

        if len(priority_2_non_answered) > 0:
            all_important_missing = missing_info & IMPORTANT_MISSING_TYPES
            if all_important_missing:
                logger.debug(
                    f"Found {len(priority_2_non_answered)} priority-2 questions "
                    f"for compliance check"
                )
                return {
                    "awaiting_clarification": True,
                    "pending_calculations": [],
                    "reasoning_chain": add_reasoning_step(
                        state,
                        f"Need clarification for compliance: {len(priority_2_non_answered)} questions",
                    ),
                }

    if _has_pending_calculations(state):
        pending = _determine_pending_calculations(state)
        if pending:
            logger.debug(f"Proceeding to calculator: {pending}")
            return {
                "awaiting_clarification": False,
                "pending_calculations": pending,
                "reasoning_chain": add_reasoning_step(
                    state,
                    f"Proceeding with {len(pending)} calculations: {', '.join(pending)}",
                ),
            }

    logger.debug("Skipping calculator, proceeding to reasoner")
    return {
        "awaiting_clarification": False,
        "pending_calculations": [],
        "reasoning_chain": add_reasoning_step(
            state,
            "No calculations needed, proceeding to reasoning",
        ),
    }


def get_routing_decision(state: AgentState) -> str:
    """
    Get the routing decision based on state.

    Used as conditional edge function in LangGraph.

    Returns:
        One of: "needs_clarification", "proceed_to_calculator", "skip_calculator"
    """
    awaiting = state.get("awaiting_clarification", False)
    pending = state.get("pending_calculations", [])

    if awaiting:
        return "needs_clarification"
    elif pending:
        return "proceed_to_calculator"
    else:
        return "skip_calculator"
