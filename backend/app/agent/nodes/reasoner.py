"""Reasoner node for synthesizing final answers."""

from __future__ import annotations

import logging
from typing import Any

from openai import AsyncOpenAI

from app.config import get_settings
from app.agent.state import (
    AgentState,
    ConfidenceLevel,
    MissingInfoType,
    QueryType,
    add_reasoning_step,
)
from app.agent.prompts.reasoner import (
    REASONER_SYSTEM_PROMPT,
    build_reasoner_prompt,
)

logger = logging.getLogger(__name__)


TEMPORAL_KEYWORDS = [
    "original dwellinghouse",
    "original house",
    "as first built",
    "1st july 1948",
    "1 july 1948",
    "as it stood",
]


def _check_for_temporal_issues(
    rules: list[dict],
    drawing_ctx: dict | None,
) -> list[str]:
    """Backup check for temporal issues in rules."""
    caveats = []

    if not drawing_ctx:
        return caveats

    is_original_confirmed = drawing_ctx.get("is_original_house") is not None

    for rule in rules:
        text = rule.get("text", "").lower()
        for keyword in TEMPORAL_KEYWORDS:
            if keyword in text:
                if not is_original_confirmed:
                    caveat = (
                        "This assessment references the 'original' house. "
                        "If your property has been extended before, "
                        "your actual allowance may be less than calculated."
                    )
                    if caveat not in caveats:
                        caveats.append(caveat)
                    break

    return caveats


def _determine_confidence(state: AgentState) -> str:
    """Determine confidence level based on state."""
    missing = set(state.get("missing_info", []))
    assumptions = state.get("assumptions", [])

    if MissingInfoType.ORIGINAL_HOUSE.value in missing:
        return ConfidenceLevel.LOW.value

    low_confidence_assumptions = [
        a for a in assumptions
        if a.get("confidence") == ConfidenceLevel.LOW.value
        and a.get("can_invalidate_answer", True)
    ]

    if low_confidence_assumptions:
        return ConfidenceLevel.LOW.value

    if missing or assumptions:
        return ConfidenceLevel.MEDIUM.value

    return ConfidenceLevel.HIGH.value


def _get_compliance_verdict(calculations: list[dict]) -> str | None:
    """Determine overall compliance verdict from calculations."""
    if not calculations:
        return None

    all_compliant = all(
        c.get("compliant", True)
        for c in calculations
        if c.get("compliant") is not None
    )

    has_any_check = any(c.get("compliant") is not None for c in calculations)

    if not has_any_check:
        return None

    return "COMPLIANT" if all_compliant else "NON_COMPLIANT"


async def reasoner_node(
    state: AgentState,
    openai_client: AsyncOpenAI | None = None,
) -> dict[str, Any]:
    """
    Synthesize a final answer from all gathered context.

    This is the main reasoning node that combines:
    - Retrieved regulations
    - Drawing context
    - Calculation results
    - Assumptions made

    Into a coherent, grounded answer.

    Args:
        state: Current agent state with all context
        openai_client: Optional OpenAI client for LLM

    Returns:
        State updates with final_answer, confidence, and additional caveats
    """
    settings = get_settings()
    query = state.get("user_query", "")
    query_type = state.get("query_type", QueryType.GENERAL.value)

    rules = state.get("retrieved_rules", [])
    exceptions = state.get("applicable_exceptions", [])
    definitions = state.get("global_definitions", {})
    drawing_ctx = state.get("drawing_context")
    calculations = state.get("calculation_results", [])
    assumptions = state.get("assumptions", [])
    existing_caveats = list(state.get("caveats", []))

    temporal_caveats = _check_for_temporal_issues(rules, drawing_ctx)
    for caveat in temporal_caveats:
        if caveat not in existing_caveats:
            existing_caveats.append(caveat)

    # Check for off-topic queries before calling LLM (saves tokens & gives better UX)
    if not rules and _is_off_topic_query(query):
        greeting_response = (
            "Hello! I'm Shapy, your UK planning permission assistant. "
            "I specialize in Permitted Development rights and can help you with questions like:\n\n"
            "- What extensions are allowed under Permitted Development?\n"
            "- What are the height limits for a rear extension?\n"
            "- Does my property comply with the 50% rule?\n\n"
            "How can I help you with your planning question today?"
        )
        return {
            "final_answer": greeting_response,
            "confidence": ConfidenceLevel.HIGH.value,
            "compliance_verdict": None,
            "suggested_followups": [
                "What are the rules for rear extensions?",
                "How do I check if I need planning permission?",
            ],
            "caveats": [],
            "reasoning_chain": add_reasoning_step(state, "Responded to greeting/off-topic query"),
        }

    user_prompt = build_reasoner_prompt(
        query=query,
        definitions=definitions,
        rules=rules,
        exceptions=exceptions,
        drawing_ctx=drawing_ctx,
        calculations=calculations,
        assumptions=assumptions,
        include_anti_hallucination=True,
    )

    final_answer: str

    if openai_client:
        try:
            response = await openai_client.chat.completions.create(
                model=settings.agent_model,
                messages=[
                    {"role": "system", "content": REASONER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=settings.agent_temperature,
                max_tokens=settings.agent_max_tokens,
            )

            final_answer = response.choices[0].message.content or ""
            final_answer = final_answer.strip()

            logger.debug(f"Generated answer: {len(final_answer)} chars")

        except Exception as e:
            logger.error(f"Reasoner LLM call failed: {e}")
            final_answer = _generate_fallback_answer(
                query=query,
                query_type=query_type,
                rules=rules,
                calculations=calculations,
            )
            existing_caveats.append(
                "Note: This is a simplified response due to a technical issue. "
                "For a full assessment, please try again."
            )
    else:
        final_answer = _generate_fallback_answer(
            query=query,
            query_type=query_type,
            rules=rules,
            calculations=calculations,
        )

    confidence = _determine_confidence(state)
    verdict = _get_compliance_verdict(calculations)

    suggested_followups = _generate_followups(state, verdict)

    reasoning = f"Generated answer with {confidence} confidence"
    if verdict:
        reasoning += f", verdict: {verdict}"
    if len(rules) > 0:
        reasoning += f", citing {len(rules)} rules"

    return {
        "final_answer": final_answer,
        "confidence": confidence,
        "caveats": existing_caveats,
        "suggested_followups": suggested_followups,
        "reasoning_chain": add_reasoning_step(state, reasoning),
    }


def _is_off_topic_query(query: str) -> bool:
    """Check if the query is off-topic (not about UK planning/building)."""
    query_lower = query.lower().strip()

    # Greetings and conversational patterns
    greeting_patterns = [
        "hi", "hello", "hey", "good morning", "good afternoon", "good evening",
        "what's up", "whats up", "how are you", "how r u", "sup",
        "what are you", "who are you", "what can you do",
    ]

    for pattern in greeting_patterns:
        if query_lower == pattern or query_lower.startswith(pattern + " ") or query_lower.startswith(pattern + "?"):
            return True

    # Very short queries without planning-related keywords
    planning_keywords = [
        "planning", "permission", "extension", "build", "house", "property",
        "development", "permitted", "boundary", "height", "depth", "area",
        "garage", "shed", "conservatory", "loft", "roof", "wall", "fence",
        "garden", "patio", "deck", "outbuilding", "annexe", "convert",
        "regulation", "rule", "limit", "maximum", "minimum", "comply",
    ]

    if len(query_lower) < 20:
        has_planning_keyword = any(kw in query_lower for kw in planning_keywords)
        if not has_planning_keyword:
            return True

    return False


def _generate_fallback_answer(
    query: str,
    query_type: str,
    rules: list[dict],
    calculations: list[dict],
) -> str:
    """Generate a basic fallback answer without LLM."""
    parts = []

    if not rules:
        # Check if this is an off-topic/conversational query
        if _is_off_topic_query(query):
            return (
                "I'm a UK planning permission assistant, specializing in Permitted Development rights. "
                "I can help you with questions like:\n\n"
                "- What extensions are allowed under Permitted Development?\n"
                "- What are the height limits for a rear extension?\n"
                "- Does my property comply with the 50% rule?\n\n"
                "How can I help you with your planning question?"
            )

        parts.append(
            "I found limited information about your question in my knowledge base. "
            "For specific guidance, please consult your local planning authority."
        )
        return "\n\n".join(parts)

    parts.append("Based on the regulations I found:")

    for rule in rules[:3]:
        section = rule.get("section", "")
        text = rule.get("text", "")
        if section and text:
            preview = text[:200] + "..." if len(text) > 200 else text
            parts.append(f"\n**{section}**: {preview}")

    if calculations:
        parts.append("\n\n**Calculations:**")
        for calc in calculations:
            calc_type = calc.get("calculation_type", "")
            result = calc.get("result", 0)
            unit = calc.get("unit", "")
            compliant = calc.get("compliant")

            status = ""
            if compliant is not None:
                status = " (Compliant)" if compliant else " (Non-compliant)"

            parts.append(f"- {calc_type}: {result}{unit}{status}")

    parts.append(
        "\n\nFor a complete assessment, please verify this information "
        "with your local planning authority."
    )

    return "\n".join(parts)


def _generate_followups(
    state: AgentState,
    verdict: str | None,
) -> list[str]:
    """Generate suggested follow-up questions or actions."""
    followups = []
    missing = set(state.get("missing_info", []))
    query_type = state.get("query_type", "")
    drawing_ctx = state.get("drawing_context")

    if MissingInfoType.ORIGINAL_HOUSE.value in missing:
        followups.append(
            "Tell me if this is the original house or if it has been extended before"
        )

    if MissingInfoType.DESIGNATED_LAND.value in missing:
        followups.append(
            "Confirm if your property is in a Conservation Area or National Park"
        )

    if MissingInfoType.HOUSE_TYPE.value in missing:
        followups.append(
            "Let me know if your house is detached, semi-detached, or terraced"
        )

    if query_type == QueryType.LEGAL_SEARCH.value:
        if not drawing_ctx or not drawing_ctx.get("has_drawing"):
            followups.append(
                "Upload a drawing to check if your specific plans comply"
            )

    if verdict == "NON_COMPLIANT":
        followups.append(
            "Ask about alternative options or what modifications would make it compliant"
        )

    return followups[:3]
