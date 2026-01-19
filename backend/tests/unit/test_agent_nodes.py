"""Unit tests for agent graph nodes."""

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


class TestClassifierNode:
    """Tests for classifier_node."""

    @pytest.mark.asyncio
    async def test_classifies_general_query(self, mock_openai_client):
        """General queries should be classified as GENERAL."""
        from app.agent.nodes.classifier import classifier_node

        state = create_initial_state(
            session_id="test",
            user_query="What is permitted development?",
        )

        with patch("app.agent.nodes.classifier.get_settings") as mock_settings:
            mock_settings.return_value.agent_classifier_model = "gpt-4"

            result = await classifier_node(state, openai_client=mock_openai_client)

        assert result["query_type"] == QueryType.GENERAL.value
        assert "reasoning_chain" in result

    @pytest.mark.asyncio
    async def test_classifies_compliance_query(self, sample_drawing_context):
        """Compliance queries should be classified as COMPLIANCE_CHECK."""
        from app.agent.nodes.classifier import classifier_node

        state = create_initial_state(
            session_id="test",
            user_query="Is my extension compliant with the 50% rule?",
            drawing_context=sample_drawing_context,
        )

        mock_client = AsyncMock()
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = '{"query_type": "COMPLIANCE_CHECK", "intent": "check compliance", "requires_drawing": true, "confidence": "high"}'
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

        with patch("app.agent.nodes.classifier.get_settings") as mock_settings:
            mock_settings.return_value.agent_classifier_model = "gpt-4"

            result = await classifier_node(state, openai_client=mock_client)

        assert result["query_type"] == QueryType.COMPLIANCE_CHECK.value

    @pytest.mark.asyncio
    async def test_fallback_without_llm(self):
        """Should use keyword fallback when no LLM client."""
        from app.agent.nodes.classifier import classifier_node

        state = create_initial_state(
            session_id="test",
            user_query="Is my extension compliant?",
        )

        result = await classifier_node(state, openai_client=None)

        assert result["query_type"] in [
            QueryType.COMPLIANCE_CHECK.value,
            QueryType.GENERAL.value,
        ]


class TestClarificationRouterNode:
    """Tests for clarification_router_node."""

    @pytest.mark.asyncio
    async def test_routes_to_clarification_when_missing_critical_info(self):
        """Should route to clarification when critical info missing."""
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
            "drawing_context": {"has_drawing": True},
            "retrieved_rules": [],
            "reasoning_chain": [],
        }

        result = await clarification_router_node(state)

        assert result["awaiting_clarification"] is True
        assert result["pending_calculations"] == []

    @pytest.mark.asyncio
    async def test_routes_to_calculator_when_calculations_needed(
        self, sample_drawing_context
    ):
        """Should route to calculator when drawings present and calculations needed."""
        from app.agent.nodes.clarification_router import clarification_router_node

        state: AgentState = {
            "session_id": "test",
            "user_query": "Is my extension compliant with 50% rule?",
            "query_type": QueryType.COMPLIANCE_CHECK.value,
            "missing_info": [],
            "clarification_questions": [],
            "drawing_context": sample_drawing_context.model_dump(),
            "retrieved_rules": [
                {"text": "must not exceed 50% of the curtilage", "section": "A.1(b)"}
            ],
            "reasoning_chain": [],
        }

        result = await clarification_router_node(state)

        assert result["awaiting_clarification"] is False
        assert "coverage_percentage" in result["pending_calculations"]

    @pytest.mark.asyncio
    async def test_skips_calculator_for_general_queries(self):
        """General queries should skip calculator."""
        from app.agent.nodes.clarification_router import clarification_router_node

        state: AgentState = {
            "session_id": "test",
            "user_query": "What is permitted development?",
            "query_type": QueryType.GENERAL.value,
            "missing_info": [],
            "clarification_questions": [],
            "drawing_context": None,
            "retrieved_rules": [],
            "reasoning_chain": [],
        }

        result = await clarification_router_node(state)

        assert result["awaiting_clarification"] is False
        assert result["pending_calculations"] == []


class TestCalculatorNode:
    """Tests for calculator_node."""

    @pytest.mark.asyncio
    async def test_calculates_coverage_percentage(self, sample_drawing_context):
        """Should calculate coverage percentage from drawing."""
        from app.agent.nodes.calculator import calculator_node

        state: AgentState = {
            "session_id": "test",
            "drawing_context": sample_drawing_context.model_dump(),
            "pending_calculations": ["coverage_percentage"],
            "reasoning_chain": [],
        }

        result = await calculator_node(state)

        assert len(result["calculation_results"]) == 1
        calc = result["calculation_results"][0]
        assert calc["calculation_type"] == "coverage_percentage"
        assert calc["result"] == 40.0
        assert calc["limit"] == 50.0
        assert calc["compliant"] is True

    @pytest.mark.asyncio
    async def test_calculates_boundary_distance(self, sample_drawing_context):
        """Should check boundary distance."""
        from app.agent.nodes.calculator import calculator_node

        state: AgentState = {
            "session_id": "test",
            "drawing_context": sample_drawing_context.model_dump(),
            "pending_calculations": ["boundary_distance"],
            "reasoning_chain": [],
        }

        result = await calculator_node(state)

        assert len(result["calculation_results"]) == 1
        calc = result["calculation_results"][0]
        assert calc["calculation_type"] == "boundary_distance"
        assert calc["compliant"] is True

    @pytest.mark.asyncio
    async def test_handles_no_drawing(self):
        """Should handle missing drawing gracefully."""
        from app.agent.nodes.calculator import calculator_node

        state: AgentState = {
            "session_id": "test",
            "drawing_context": None,
            "pending_calculations": ["coverage_percentage"],
            "reasoning_chain": [],
        }

        result = await calculator_node(state)

        assert result["calculation_results"] == []

    @pytest.mark.asyncio
    async def test_detects_invalid_geometry(self):
        """Should detect impossible geometry (building > plot)."""
        from app.agent.nodes.calculator import calculator_node

        invalid_context = {
            "has_drawing": True,
            "plot_area_sqm": 100.0,
            "building_footprint_sqm": 150.0,
        }

        state: AgentState = {
            "session_id": "test",
            "drawing_context": invalid_context,
            "pending_calculations": ["coverage_percentage"],
            "errors": [],
            "reasoning_chain": [],
        }

        result = await calculator_node(state)

        assert result.get("should_escalate") is True
        assert len(result.get("errors", [])) > 0


class TestAssumptionAnalyzerNode:
    """Tests for assumption_analyzer_node."""

    @pytest.mark.asyncio
    async def test_detects_temporal_definition(
        self, sample_retrieved_rule_50_percent, sample_drawing_context_no_original
    ):
        """Should detect 'original dwellinghouse' and flag for clarification."""
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
            "original" in q["question"].lower()
            for q in result["clarification_questions"]
        )

    @pytest.mark.asyncio
    async def test_no_clarification_when_context_provided(
        self, sample_retrieved_rule_50_percent, sample_drawing_context
    ):
        """Should not ask for clarification when context already provided."""
        from app.agent.nodes.assumption_analyzer import assumption_analyzer_node

        state: AgentState = {
            "session_id": "test",
            "query_type": QueryType.COMPLIANCE_CHECK.value,
            "drawing_context": sample_drawing_context.model_dump(),
            "retrieved_rules": [sample_retrieved_rule_50_percent],
            "assumptions": [],
            "missing_info": [],
            "clarification_questions": [],
            "caveats": [],
            "reasoning_chain": [],
        }

        result = await assumption_analyzer_node(state)

        original_house_questions = [
            q for q in result.get("clarification_questions", [])
            if q.get("field_name") == "is_original_house"
        ]
        assert len(original_house_questions) == 0

    @pytest.mark.asyncio
    async def test_detects_designated_land_reference(
        self, sample_retrieved_rule_designated, sample_drawing_context_no_original
    ):
        """Should detect designated land references."""
        from app.agent.nodes.assumption_analyzer import assumption_analyzer_node

        state: AgentState = {
            "session_id": "test",
            "query_type": QueryType.COMPLIANCE_CHECK.value,
            "drawing_context": sample_drawing_context_no_original.model_dump(),
            "retrieved_rules": [sample_retrieved_rule_designated],
            "assumptions": [],
            "missing_info": [],
            "clarification_questions": [],
            "caveats": [],
            "reasoning_chain": [],
        }

        result = await assumption_analyzer_node(state)

        assert MissingInfoType.DESIGNATED_LAND.value in result["missing_info"]


class TestClarifierNode:
    """Tests for clarifier_node."""

    @pytest.mark.asyncio
    async def test_generates_clarification_message(self, mock_openai_client):
        """Should generate user-friendly clarification message."""
        from app.agent.nodes.clarifier import clarifier_node

        state: AgentState = {
            "session_id": "test",
            "user_query": "Is my extension compliant?",
            "clarification_questions": [
                {
                    "id": "clarify_original_house",
                    "question": "Is this the original house?",
                    "why_needed": "For 50% calculation",
                    "field_name": "is_original_house",
                    "options": [
                        {"label": "Yes", "value": "true"},
                        {"label": "No", "value": "false"},
                    ],
                    "priority": 1,
                    "answered": False,
                }
            ],
            "reasoning_chain": [],
        }

        with patch("app.agent.nodes.clarifier.get_settings") as mock_settings:
            mock_settings.return_value.agent_clarifier_model = "gpt-4"

            result = await clarifier_node(state, openai_client=mock_openai_client)

        assert result["awaiting_clarification"] is True
        assert result["final_answer"] is not None
        assert len(result["final_answer"]) > 0

    @pytest.mark.asyncio
    async def test_fallback_without_llm(self):
        """Should generate fallback message without LLM."""
        from app.agent.nodes.clarifier import clarifier_node

        state: AgentState = {
            "session_id": "test",
            "user_query": "Is my extension compliant?",
            "clarification_questions": [
                {
                    "id": "clarify_original_house",
                    "question": "Is this the original house as built?",
                    "why_needed": "For calculation",
                    "field_name": "is_original_house",
                    "options": None,
                    "priority": 1,
                    "answered": False,
                }
            ],
            "reasoning_chain": [],
        }

        result = await clarifier_node(state, openai_client=None)

        assert "original house" in result["final_answer"].lower()


class TestResponseFormatterNode:
    """Tests for response_formatter_node."""

    @pytest.mark.asyncio
    async def test_adds_assumptions_section(self):
        """Should add assumptions section when assumptions made."""
        from app.agent.nodes.response_formatter import response_formatter_node

        state: AgentState = {
            "final_answer": "Your extension is compliant.",
            "assumptions": [
                {
                    "id": "assumed_original",
                    "description": "Assuming is_original_house = True",
                    "field_name": "is_original_house",
                    "assumed_value": True,
                    "confidence": "low",
                    "source": "default",
                    "affects_rules": ["A.1(b)"],
                    "can_invalidate_answer": True,
                }
            ],
            "caveats": [],
            "confidence": ConfidenceLevel.MEDIUM.value,
            "suggested_followups": [],
            "reasoning_chain": [],
        }

        result = await response_formatter_node(state)

        assert "Assumptions Made" in result["final_answer"]
        assert "Disclaimer" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_adds_caveats_section(self):
        """Should add caveats section when caveats present."""
        from app.agent.nodes.response_formatter import response_formatter_node

        state: AgentState = {
            "final_answer": "Your extension appears compliant.",
            "assumptions": [],
            "caveats": [
                "This assessment assumes the drawing shows the ORIGINAL house."
            ],
            "confidence": ConfidenceLevel.LOW.value,
            "suggested_followups": [],
            "reasoning_chain": [],
        }

        result = await response_formatter_node(state)

        assert "Important Caveats" in result["final_answer"]
        assert "ORIGINAL house" in result["final_answer"]

    @pytest.mark.asyncio
    async def test_includes_confidence_indicator(self):
        """Should include confidence level."""
        from app.agent.nodes.response_formatter import response_formatter_node

        state: AgentState = {
            "final_answer": "Here is your answer.",
            "assumptions": [],
            "caveats": [],
            "confidence": ConfidenceLevel.HIGH.value,
            "suggested_followups": [],
            "reasoning_chain": [],
        }

        result = await response_formatter_node(state)

        assert "Confidence" in result["final_answer"]
        assert "High" in result["final_answer"]


class TestClarificationResponseParsing:
    """Tests for parsing user clarification responses."""

    def test_parses_yes_response(self):
        """Should parse 'yes' as True for boolean questions."""
        from app.agent.nodes.clarifier import parse_clarification_response

        questions = [
            {
                "id": "clarify_original_house",
                "question": "Is this the original house?",
                "field_name": "is_original_house",
                "options": [
                    {"label": "Yes, this is the original house", "value": "true"},
                    {"label": "No, it has been extended", "value": "false"},
                ],
                "answered": False,
            }
        ]

        result = parse_clarification_response(
            "Yes, this is the original house",
            questions,
        )

        assert result.get("is_original_house") is True
        assert questions[0]["answered"] is True

    def test_parses_numeric_response(self):
        """Should extract numbers from responses."""
        from app.agent.nodes.clarifier import parse_clarification_response

        questions = [
            {
                "id": "clarify_prior_extensions",
                "question": "How much area was added?",
                "field_name": "prior_extensions_sqm",
                "options": None,
                "answered": False,
            }
        ]

        result = parse_clarification_response(
            "About 15 square metres",
            questions,
        )

        assert result.get("prior_extensions_sqm") == 15.0
