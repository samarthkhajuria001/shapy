"""LangGraph definition for the AI agent workflow."""

from __future__ import annotations

import logging
from functools import partial
from typing import Any, Literal

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver
from langchain_core.runnables import RunnableConfig

from app.agent.state import AgentState, QueryType

logger = logging.getLogger(__name__)


def _extract_openai_client(config: RunnableConfig | None):
    """Extract OpenAI client from LangGraph config."""
    if config is None:
        return None
    configurable = config.get("configurable", {})
    return configurable.get("openai_client")


def route_by_query_type(state: AgentState) -> str:
    """Route based on classified query type.

    Returns:
        Route key: "general", "legal_search", "compliance_check", or "calculation"
    """
    query_type = state.get("query_type", QueryType.GENERAL.value)

    if query_type == QueryType.GENERAL.value:
        return "general"
    elif query_type == QueryType.LEGAL_SEARCH.value:
        return "legal_search"
    elif query_type == QueryType.COMPLIANCE_CHECK.value:
        return "compliance_check"
    elif query_type == QueryType.CALCULATION.value:
        return "calculation"
    elif query_type == QueryType.CLARIFICATION_RESPONSE.value:
        return "clarification_response"
    else:
        return "general"


def route_by_missing_info(state: AgentState) -> str:
    """Route based on whether clarification is needed.

    Returns:
        Route key: "needs_clarification", "proceed_to_calculator", or "skip_calculator"
    """
    awaiting = state.get("awaiting_clarification", False)
    pending = state.get("pending_calculations", [])

    if awaiting:
        return "needs_clarification"
    elif pending:
        return "proceed_to_calculator"
    else:
        return "skip_calculator"


def create_agent_graph(use_checkpointer: bool = False) -> StateGraph:
    """
    Create the LangGraph workflow for the AI agent.

    Graph structure:
    ```
    [ENTRY] -> classifier
                   |
            +-----------------+
            |        |        |
            v        v        v
         general  legal_*  compliance_*
            |        |        |
            |        v        v
            |   context_loader
            |        |
            |        v
            |    retriever
            |        |
            |        v
            |  assumption_analyzer
            |        |
            |        v
            |  clarification_router
            |        |
            +---+---------+--------+
                |         |        |
                v         v        v
           clarifier  calculator  reasoner
                |         |        |
                v         v        |
              [END]   validator    |
                          |        |
                          +--------+
                                 |
                                 v
                          response_formatter
                                 |
                                 v
                              [END]
    ```

    Args:
        use_checkpointer: Whether to use memory checkpointing for persistence

    Returns:
        Compiled StateGraph ready for execution
    """
    from app.agent.nodes.classifier import classifier_node
    from app.agent.nodes.context_loader import context_loader_node
    from app.agent.nodes.retriever import retriever_node
    from app.agent.nodes.assumption_analyzer import assumption_analyzer_node
    from app.agent.nodes.clarification_router import clarification_router_node
    from app.agent.nodes.clarifier import clarifier_node
    from app.agent.nodes.calculator import calculator_node
    from app.agent.nodes.validator import validator_node
    from app.agent.nodes.reasoner import reasoner_node
    from app.agent.nodes.response_formatter import response_formatter_node

    # Create wrapper functions that extract openai_client from config
    async def classifier_with_config(state: AgentState, config: RunnableConfig) -> dict:
        openai_client = _extract_openai_client(config)
        return await classifier_node(state, openai_client)

    async def clarifier_with_config(state: AgentState, config: RunnableConfig) -> dict:
        openai_client = _extract_openai_client(config)
        return await clarifier_node(state, openai_client)

    async def reasoner_with_config(state: AgentState, config: RunnableConfig) -> dict:
        openai_client = _extract_openai_client(config)
        return await reasoner_node(state, openai_client)

    graph = StateGraph(AgentState)

    # Nodes that need OpenAI client use wrapped versions
    graph.add_node("classifier", classifier_with_config)
    graph.add_node("context_loader", context_loader_node)
    graph.add_node("retriever", retriever_node)
    graph.add_node("assumption_analyzer", assumption_analyzer_node)
    graph.add_node("clarification_router", clarification_router_node)
    graph.add_node("clarifier", clarifier_with_config)
    graph.add_node("calculator", calculator_node)
    graph.add_node("validator", validator_node)
    graph.add_node("reasoner", reasoner_with_config)
    graph.add_node("response_formatter", response_formatter_node)

    graph.set_entry_point("classifier")

    graph.add_conditional_edges(
        "classifier",
        route_by_query_type,
        {
            "general": "reasoner",
            "legal_search": "context_loader",
            "compliance_check": "context_loader",
            "calculation": "context_loader",
            "clarification_response": "context_loader",
        }
    )

    graph.add_edge("context_loader", "retriever")
    graph.add_edge("retriever", "assumption_analyzer")
    graph.add_edge("assumption_analyzer", "clarification_router")

    graph.add_conditional_edges(
        "clarification_router",
        route_by_missing_info,
        {
            "needs_clarification": "clarifier",
            "proceed_to_calculator": "calculator",
            "skip_calculator": "reasoner",
        }
    )

    graph.add_edge("clarifier", END)

    graph.add_edge("calculator", "validator")
    graph.add_edge("validator", "reasoner")

    graph.add_edge("reasoner", "response_formatter")

    graph.add_edge("response_formatter", END)

    checkpointer = None
    if use_checkpointer:
        checkpointer = MemorySaver()

    return graph.compile(checkpointer=checkpointer)


_compiled_graph = None


def get_agent_graph(use_checkpointer: bool = False) -> StateGraph:
    """Get or create the singleton agent graph.

    Args:
        use_checkpointer: Whether to enable memory checkpointing

    Returns:
        Compiled agent graph
    """
    global _compiled_graph

    if _compiled_graph is None:
        _compiled_graph = create_agent_graph(use_checkpointer=use_checkpointer)
        logger.info("Agent graph compiled successfully")

    return _compiled_graph


def reset_agent_graph() -> None:
    """Reset the singleton graph. Useful for testing."""
    global _compiled_graph
    _compiled_graph = None
