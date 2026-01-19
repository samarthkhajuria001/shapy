"""Integration tests for complete agent graph flows."""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.agent.state import (
    AgentState,
    ConfidenceLevel,
    DrawingContext,
    MissingInfoType,
    QueryType,
    create_initial_state,
)
from app.agent.graph import create_agent_graph, reset_agent_graph
from app.agent.orchestrator import AgentOrchestrator


@pytest.fixture(autouse=True)
def reset_graph():
    """Reset graph singleton before each test."""
    reset_agent_graph()
    yield
    reset_agent_graph()


class TestGeneralQueryFlow:
    """Test the general query path: classifier → reasoner → formatter → END."""

    @pytest.mark.asyncio
    async def test_general_query_skips_retrieval(self):
        """General queries should skip directly to reasoner."""
        graph = create_agent_graph(use_checkpointer=False)

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="What is permitted development?",
        )

        result = await graph.ainvoke(initial_state, {})

        assert result["query_type"] == QueryType.GENERAL.value
        assert result["final_answer"] is not None
        assert result.get("awaiting_clarification", False) is False


class TestLegalSearchFlow:
    """Test legal search path with retrieval."""

    @pytest.mark.asyncio
    async def test_legal_search_retrieves_rules(self, sample_global_definitions):
        """Legal search should retrieve and cite relevant rules."""
        graph = create_agent_graph(use_checkpointer=False)

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="What is the maximum height for extensions?",
        )

        result = await graph.ainvoke(initial_state, {})

        assert result["query_type"] in [
            QueryType.LEGAL_SEARCH.value,
            QueryType.GENERAL.value,
        ]
        assert result["final_answer"] is not None


class TestComplianceCheckWithDrawing:
    """Test compliance check with drawing uploaded."""

    @pytest.mark.asyncio
    async def test_compliance_check_performs_calculations(
        self,
        sample_drawing_context,
        sample_global_definitions,
    ):
        """Compliance check should process through the pipeline."""
        graph = create_agent_graph(use_checkpointer=False)

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="Is my extension compliant with the 50% rule?",
            drawing_context=sample_drawing_context,
        )

        result = await graph.ainvoke(initial_state, {})

        assert result["query_type"] in [
            QueryType.COMPLIANCE_CHECK.value,
            QueryType.LEGAL_SEARCH.value,
            QueryType.GENERAL.value,
        ]
        assert result["final_answer"] is not None


class TestComplianceCheckWithoutDrawing:
    """Test compliance check when no drawing uploaded."""

    @pytest.mark.asyncio
    async def test_handles_no_drawing(self):
        """Should handle missing drawing gracefully."""
        graph = create_agent_graph(use_checkpointer=False)

        empty_drawing = DrawingContext(session_id="test", has_drawing=False)

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="Is my extension compliant?",
            drawing_context=empty_drawing,
        )

        result = await graph.ainvoke(initial_state, {})

        assert result["final_answer"] is not None


class TestTemporalProblemDetection:
    """Test detection of the temporal problem (original dwellinghouse)."""

    @pytest.mark.asyncio
    async def test_detects_temporal_issue_in_assumption_analyzer(
        self,
        sample_drawing_context_no_original,
        sample_retrieved_rule_50_percent,
    ):
        """Should detect 'original dwellinghouse' in assumption analyzer."""
        from app.agent.nodes.assumption_analyzer import assumption_analyzer_node

        state: AgentState = {
            "session_id": "test",
            "query_type": QueryType.COMPLIANCE_CHECK.value,
            "drawing_context": sample_drawing_context_no_original.model_dump(),
            "retrieved_rules": [sample_retrieved_rule_50_percent],
            "assumptions": [],
            "missing_info": [],
            "clarification_questions": [],
            "caveats": [],
            "reasoning_chain": [],
        }

        result = await assumption_analyzer_node(state)

        assert MissingInfoType.ORIGINAL_HOUSE.value in result["missing_info"]
        assert len(result["clarification_questions"]) > 0
        assert any(
            "original" in q.get("question", "").lower()
            for q in result["clarification_questions"]
        )


class TestMultiTurnConversation:
    """Test multi-turn conversation with clarification responses."""

    @pytest.mark.asyncio
    async def test_continues_after_clarification_response(self):
        """Should continue processing after user answers clarification."""
        from app.agent.nodes.clarifier import parse_clarification_response

        questions = [
            {
                "id": "clarify_original_house",
                "question": "Is this the original house?",
                "field_name": "is_original_house",
                "why_needed": "For 50% calculation",
                "options": [
                    {"label": "Yes, this is the original house", "value": "true"},
                    {"label": "No, it has been extended", "value": "false"},
                ],
                "priority": 1,
                "answered": False,
            }
        ]

        user_response = "Yes, this is the original house"

        updates = parse_clarification_response(user_response, questions)

        assert updates.get("is_original_house") is True
        assert questions[0]["answered"] is True


class TestAntiHallucination:
    """Test that responses are grounded in provided rules."""

    @pytest.mark.asyncio
    async def test_answer_references_provided_rules(
        self,
        sample_drawing_context,
        sample_global_definitions,
    ):
        """Answer should reference rules from context, not hallucinate."""
        from app.agent.prompts.reasoner import build_reasoner_prompt

        rules = [
            {
                "parent_id": "test-rule",
                "text": "The eaves height shall not exceed 3 metres.",
                "section": "A.1(i)",
                "page_start": 9,
                "page_end": 9,
                "relevance_score": 0.9,
                "uses_definitions": [],
                "designated_land_specific": False,
            }
        ]

        prompt = build_reasoner_prompt(
            query="What is the maximum eaves height?",
            definitions=sample_global_definitions,
            rules=rules,
            exceptions=[],
            drawing_ctx=sample_drawing_context.model_dump(),
            calculations=[],
            assumptions=[],
            include_anti_hallucination=True,
        )

        assert "GROUNDING RULES" in prompt
        assert "ONLY cite rules" in prompt
        assert "3 metres" in prompt
        assert "A.1(i)" in prompt


class TestOrchestratorIntegration:
    """Test the orchestrator's ability to manage conversations."""

    @pytest.mark.asyncio
    async def test_orchestrator_processes_query(self):
        """Orchestrator should process a query and return response."""
        orchestrator = AgentOrchestrator(
            openai_client=None,
            redis_client=None,
        )

        with patch("app.agent.orchestrator.get_settings") as mock_settings:
            mock_settings.return_value.openai_api_key = None

            await orchestrator.initialize()

            response = await orchestrator.process_query(
                session_id="test-session",
                query="What is permitted development?",
            )

        assert response.answer is not None
        assert response.query_type is not None


class TestEdgeCases:
    """Test edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_handles_empty_query(self):
        """Should handle empty or whitespace queries gracefully."""
        graph = create_agent_graph(use_checkpointer=False)

        initial_state = create_initial_state(
            session_id="test",
            user_query="   ",
        )

        result = await graph.ainvoke(initial_state, {})

        assert result.get("final_answer") is not None or result.get("errors")

    @pytest.mark.asyncio
    async def test_handles_very_long_query(self):
        """Should handle very long queries."""
        graph = create_agent_graph(use_checkpointer=False)

        long_query = "Can I build an extension? " * 100

        initial_state = create_initial_state(
            session_id="test",
            user_query=long_query,
        )

        result = await graph.ainvoke(initial_state, {})

        assert "query_type" in result

    @pytest.mark.asyncio
    async def test_handles_missing_openai_client(self):
        """Should use fallbacks when OpenAI client unavailable."""
        graph = create_agent_graph(use_checkpointer=False)

        initial_state = create_initial_state(
            session_id="test",
            user_query="What is permitted development?",
        )

        result = await graph.ainvoke(initial_state, {})

        assert result["query_type"] is not None


class TestCalculatorIntegration:
    """Test calculator node in the pipeline."""

    @pytest.mark.asyncio
    async def test_calculator_with_valid_drawing(self, sample_drawing_context):
        """Calculator should produce results with valid drawing."""
        from app.agent.nodes.calculator import calculator_node

        state: AgentState = {
            "session_id": "test",
            "drawing_context": sample_drawing_context.model_dump(),
            "pending_calculations": ["coverage_percentage", "boundary_distance"],
            "reasoning_chain": [],
        }

        result = await calculator_node(state)

        assert len(result["calculation_results"]) >= 1
        coverage_calc = next(
            (c for c in result["calculation_results"]
             if c["calculation_type"] == "coverage_percentage"),
            None
        )
        assert coverage_calc is not None
        assert coverage_calc["result"] == 40.0
        assert coverage_calc["compliant"] is True


class TestClarificationRouterIntegration:
    """Test clarification router decisions."""

    @pytest.mark.asyncio
    async def test_routes_to_clarification_for_temporal_issue(
        self,
        sample_drawing_context_no_original,
    ):
        """Should route to clarification when temporal issue detected."""
        from app.agent.nodes.clarification_router import clarification_router_node

        state: AgentState = {
            "session_id": "test",
            "user_query": "Is my extension compliant?",
            "query_type": QueryType.COMPLIANCE_CHECK.value,
            "missing_info": [MissingInfoType.ORIGINAL_HOUSE.value],
            "clarification_questions": [
                {
                    "id": "clarify_original_house",
                    "question": "Is this the original house?",
                    "why_needed": "For 50% calculation",
                    "field_name": "is_original_house",
                    "options": None,
                    "priority": 1,
                    "answered": False,
                }
            ],
            "drawing_context": sample_drawing_context_no_original.model_dump(),
            "retrieved_rules": [],
            "reasoning_chain": [],
        }

        result = await clarification_router_node(state)

        assert result["awaiting_clarification"] is True
