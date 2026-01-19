"""Retriever node for fetching relevant rules from knowledge base."""

import logging
from typing import Any

from app.agent.state import (
    AgentState,
    RetrievedRule,
    add_reasoning_step,
)
from app.services.retrieval.retriever import RetrieverService, RetrievalResult
from app.services.retrieval.xref_resolver import EnhancedParent

logger = logging.getLogger(__name__)

GLOBAL_DEFINITIONS = {
    "original dwellinghouse": (
        "The house as it was first built, or as it stood on 1st July 1948 "
        "(whichever is later). Any extensions built after that date are not "
        "considered part of the original house for calculating limits."
    ),
    "curtilage": (
        "The area of land around a house that is used for the enjoyment of the "
        "dwelling. This typically includes gardens, driveways, and outbuildings."
    ),
    "principal elevation": (
        "The elevation that faces a highway and forms the main or front of the "
        "house. Usually the elevation containing the main entrance."
    ),
    "article 2(3) land": (
        "Designated land including Conservation Areas, Areas of Outstanding "
        "Natural Beauty (AONBs), National Parks, the Broads, and World Heritage Sites. "
        "Stricter permitted development rules apply."
    ),
    "highway": (
        "Any road, lane, or path to which the public has access. Includes both "
        "public highways and private roads with public rights of way."
    ),
}


def _convert_enhanced_parent_to_rule(
    parent: EnhancedParent,
    is_exception: bool = False,
) -> RetrievedRule:
    """Convert Phase 3 EnhancedParent to RetrievedRule model."""
    data = parent.parent_data
    content_index = data.get("content_index", {})

    sections = content_index.get("sections_covered", [])
    section = sections[0] if sections else None

    text = data.get("text", "")
    text_lower = text.lower()

    designated_land_specific = any(
        kw in text_lower
        for kw in ["article 2(3)", "conservation area", "national park",
                   "aonb", "world heritage", "the broads"]
    )

    xrefs = []
    for resolved in parent.resolved_xrefs:
        xrefs.append(resolved.section)

    return RetrievedRule(
        parent_id=parent.id,
        text=text,
        section=section,
        page_start=data.get("page_start", 0),
        page_end=data.get("page_end", 0),
        source=data.get("source", ""),
        relevance_score=parent.score,
        uses_definitions=content_index.get("definitions_used", []),
        xrefs=xrefs,
        sections_covered=sections,
        has_exceptions=is_exception or parent.is_xref_parent,
        designated_land_specific=designated_land_specific,
    )


def _extract_rules_from_result(
    result: RetrievalResult,
) -> tuple[list[dict], list[dict]]:
    """
    Extract primary rules and exceptions from retrieval result.

    Returns:
        (primary_rules, exception_rules) as list of dicts
    """
    primary_rules = []
    exception_rules = []

    for parent in result.enhanced_parents:
        rule = _convert_enhanced_parent_to_rule(
            parent,
            is_exception=parent.is_xref_parent,
        )

        if parent.is_xref_parent:
            exception_rules.append(rule.model_dump())
        else:
            primary_rules.append(rule.model_dump())

    return primary_rules, exception_rules


async def retriever_node(
    state: AgentState,
    retriever_service: RetrieverService | None = None,
) -> dict[str, Any]:
    """
    Retrieve relevant rules from the Phase 3 knowledge base.

    Args:
        state: Current agent state with user_query
        retriever_service: Optional retriever service (uses singleton if not provided)

    Returns:
        State updates with retrieved_rules, context_text, global_definitions
    """
    query = state.get("user_query", "")

    if not query:
        logger.warning("Empty query for retrieval")
        return {
            "retrieved_rules": [],
            "applicable_exceptions": [],
            "context_text": "",
            "global_definitions": GLOBAL_DEFINITIONS,
            "reasoning_chain": add_reasoning_step(state, "No query for retrieval"),
        }

    if retriever_service is None:
        try:
            from app.services.retrieval.retriever import get_retriever_service
            retriever_service = await get_retriever_service()
        except Exception as e:
            logger.error(f"Failed to get retriever service: {e}")
            return {
                "retrieved_rules": [],
                "applicable_exceptions": [],
                "context_text": "",
                "global_definitions": GLOBAL_DEFINITIONS,
                "errors": state.get("errors", []) + [f"Retriever unavailable: {e}"],
                "reasoning_chain": add_reasoning_step(
                    state,
                    "Retriever service unavailable",
                ),
            }

    try:
        result = await retriever_service.retrieve(query)
    except Exception as e:
        logger.error(f"Retrieval failed: {e}")
        return {
            "retrieved_rules": [],
            "applicable_exceptions": [],
            "context_text": "",
            "global_definitions": GLOBAL_DEFINITIONS,
            "errors": state.get("errors", []) + [f"Retrieval failed: {e}"],
            "reasoning_chain": add_reasoning_step(state, f"Retrieval error: {e}"),
        }

    if not result.enhanced_parents:
        logger.info(f"No results for query: {query[:50]}...")
        return {
            "retrieved_rules": [],
            "applicable_exceptions": [],
            "context_text": "",
            "global_definitions": GLOBAL_DEFINITIONS,
            "reasoning_chain": add_reasoning_step(
                state,
                "No relevant rules found in knowledge base",
            ),
        }

    primary_rules, exception_rules = _extract_rules_from_result(result)

    context_text = result.context.text

    primary_count = len(primary_rules)
    exception_count = len(exception_rules)
    token_count = result.context.token_count

    reasoning = (
        f"Retrieved {primary_count} rules, {exception_count} exceptions "
        f"({token_count} tokens)"
    )

    if result.context.sections_included:
        sections_preview = ", ".join(result.context.sections_included[:5])
        reasoning += f" covering {sections_preview}"

    logger.debug(reasoning)

    return {
        "retrieved_rules": primary_rules,
        "applicable_exceptions": exception_rules,
        "context_text": context_text,
        "global_definitions": GLOBAL_DEFINITIONS,
        "reasoning_chain": add_reasoning_step(state, reasoning),
    }


def get_definitions_for_rules(
    rules: list[dict],
) -> dict[str, str]:
    """
    Get relevant global definitions based on retrieved rules.

    Filters global definitions to only those referenced by the rules.

    Args:
        rules: List of RetrievedRule dicts

    Returns:
        Filtered dictionary of relevant definitions
    """
    used_definitions: set[str] = set()

    for rule in rules:
        uses_defs = rule.get("uses_definitions", [])
        for defn in uses_defs:
            used_definitions.add(defn.lower())

        text_lower = rule.get("text", "").lower()
        for key in GLOBAL_DEFINITIONS:
            if key in text_lower:
                used_definitions.add(key)

    relevant = {}
    for key, value in GLOBAL_DEFINITIONS.items():
        if key in used_definitions:
            relevant[key] = value

    if not relevant:
        return GLOBAL_DEFINITIONS

    return relevant
