"""Response formatter node for final output formatting."""

from __future__ import annotations

import logging
from typing import Any

from app.agent.state import (
    AgentState,
    ConfidenceLevel,
    add_reasoning_step,
)

logger = logging.getLogger(__name__)


CONFIDENCE_INDICATORS = {
    ConfidenceLevel.HIGH.value: "High",
    ConfidenceLevel.MEDIUM.value: "Medium",
    ConfidenceLevel.LOW.value: "Low",
}


DISCLAIMER = (
    "This is AI-generated guidance for informational purposes only, "
    "not legal advice. Always verify with your local planning authority "
    "before proceeding with any building work."
)


def _format_assumptions_section(assumptions: list[dict]) -> str | None:
    """Format assumptions into a readable section."""
    if not assumptions:
        return None

    user_stated = [a for a in assumptions if a.get("source") == "user_stated"]
    defaulted = [a for a in assumptions if a.get("source") == "default"]

    parts = []

    if defaulted:
        parts.append("**Assumptions Made:**")
        for a in defaulted:
            desc = a.get("description", "")
            if desc.startswith("Assuming "):
                desc = desc[9:]
            parts.append(f"- {desc}")

    return "\n".join(parts) if parts else None


def _format_caveats_section(caveats: list[str]) -> str | None:
    """Format caveats into a readable section."""
    if not caveats:
        return None

    parts = ["**Important Caveats:**"]
    for caveat in caveats:
        caveat_text = caveat
        if caveat.startswith("IMPORTANT: "):
            caveat_text = caveat[11:]
        parts.append(f"- {caveat_text}")

    return "\n".join(parts)


def _format_followups_section(followups: list[str]) -> str | None:
    """Format follow-up suggestions into a readable section."""
    if not followups:
        return None

    parts = ["**To get a more accurate assessment, you could:**"]
    for f in followups:
        parts.append(f"- {f}")

    return "\n".join(parts)


def _format_confidence_indicator(confidence: str) -> str:
    """Format confidence level for display."""
    label = CONFIDENCE_INDICATORS.get(confidence, "Unknown")
    return f"*Confidence: {label}*"


async def response_formatter_node(state: AgentState) -> dict[str, Any]:
    """
    Format the final response with all necessary sections.

    Adds:
    - Explicit assumptions section (if any)
    - Caveats section (if any)
    - Confidence indicator
    - Follow-up suggestions
    - Disclaimer

    Args:
        state: Current agent state with final_answer and metadata

    Returns:
        State updates with formatted final_answer
    """
    final_answer = state.get("final_answer", "")
    assumptions = state.get("assumptions", [])
    caveats = state.get("caveats", [])
    confidence = state.get("confidence", ConfidenceLevel.MEDIUM.value)
    followups = state.get("suggested_followups", [])

    if not final_answer:
        logger.warning("Response formatter called with empty final_answer")
        final_answer = (
            "I was unable to generate a complete response. "
            "Please try rephrasing your question or contact your local planning authority."
        )

    parts = [final_answer]

    assumptions_section = _format_assumptions_section(assumptions)
    if assumptions_section:
        parts.append("")
        parts.append("---")
        parts.append(assumptions_section)

    caveats_section = _format_caveats_section(caveats)
    if caveats_section:
        parts.append("")
        parts.append("---")
        parts.append(caveats_section)

    if followups:
        followups_section = _format_followups_section(followups)
        if followups_section:
            parts.append("")
            parts.append("---")
            parts.append(followups_section)

    parts.append("")
    parts.append("---")
    parts.append(_format_confidence_indicator(confidence))
    parts.append("")
    parts.append(f"*{DISCLAIMER}*")

    formatted_answer = "\n".join(parts)

    sections_added = []
    if assumptions_section:
        sections_added.append("assumptions")
    if caveats_section:
        sections_added.append("caveats")
    if followups:
        sections_added.append("followups")

    reasoning = f"Formatted response with {confidence} confidence"
    if sections_added:
        reasoning += f", added {', '.join(sections_added)}"

    return {
        "final_answer": formatted_answer,
        "reasoning_chain": add_reasoning_step(state, reasoning),
    }


def extract_raw_answer(formatted_answer: str) -> str:
    """
    Extract the main answer content without formatting sections.

    Useful for logging or when only the core answer is needed.

    Args:
        formatted_answer: Full formatted response

    Returns:
        Just the main answer text
    """
    if "---" in formatted_answer:
        parts = formatted_answer.split("---")
        if parts:
            return parts[0].strip()

    return formatted_answer.strip()
