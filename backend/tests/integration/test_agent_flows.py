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
from app.agent.orchestrator import AgentOrchestrator, process_chat_query


@pytest.fixture(autouse=True)
def reset_graph():
    """Reset graph singleton before each test."""
    reset_agent_graph()
    yield
    reset_agent_graph()


class TestGeneralQueryFlow:
    """Test the general query path: classifier → reasoner → formatter → END."""

    @pytest.mark.asyncio
    async def test_general_query_skips_retrieval(self, mock_openai_client):
        """General queries should skip directly to reasoner."""
        graph = create_agent_graph(use_checkpointer=False)

        mock_classifier_response = MagicMock()
        mock_classifier_response.choices = [MagicMock()]
        mock_classifier_response.choices[0].message.content = json.dumps({
            "query_type": "GENERAL",
            "intent": "understand what permitted development is",
            "requires_drawing": False,
            "confidence": "high",
        })

        mock_reasoner_response = MagicMock()
        mock_reasoner_response.choices = [MagicMock()]
        mock_reasoner_response.choices[0].message.content = (
            "Permitted development rights allow certain building works "
            "without needing to apply for planning permission."
        )

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return mock_classifier_response
            return mock_reasoner_response

        mock_openai_client.chat.completions.create = mock_create

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="What is permitted development?",
        )

        with patch("app.agent.nodes.classifier.get_settings") as mock_settings, \
             patch("app.agent.nodes.reasoner.get_settings") as mock_reasoner_settings:
            mock_settings.return_value.agent_classifier_model = "gpt-4"
            mock_reasoner_settings.return_value.agent_model = "gpt-4"
            mock_reasoner_settings.return_value.agent_temperature = 0.1
            mock_reasoner_settings.return_value.agent_max_tokens = 2000

            result = await graph.ainvoke(
                initial_state,
                {"configurable": {"openai_client": mock_openai_client}},
            )

        assert result["query_type"] == QueryType.GENERAL.value
        assert result["final_answer"] is not None
        assert "permitted development" in result["final_answer"].lower()
        assert result.get("awaiting_clarification", False) is False


class TestLegalSearchFlow:
    """Test legal search path with retrieval."""

    @pytest.mark.asyncio
    async def test_legal_search_retrieves_rules(
        self,
        mock_openai_client,
        mock_retriever_service,
        sample_global_definitions,
    ):
        """Legal search should retrieve and cite relevant rules."""
        graph = create_agent_graph(use_checkpointer=False)

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]

            if call_count[0] == 1:
                mock_response.choices[0].message.content = json.dumps({
                    "query_type": "LEGAL_SEARCH",
                    "intent": "find height limits for extensions",
                    "requires_drawing": False,
                    "confidence": "high",
                })
            else:
                mock_response.choices[0].message.content = (
                    "According to Class A.1(i), eaves height is limited to 3 metres "
                    "when within 2 metres of a boundary."
                )

            return mock_response

        mock_openai_client.chat.completions.create = mock_create

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="What is the maximum height for extensions?",
        )

        with patch("app.agent.nodes.classifier.get_settings") as mock_cls_settings, \
             patch("app.agent.nodes.reasoner.get_settings") as mock_rsn_settings, \
             patch("app.agent.nodes.retriever.get_retriever_service", return_value=mock_retriever_service), \
             patch("app.agent.nodes.retriever.GLOBAL_DEFINITIONS", sample_global_definitions):

            mock_cls_settings.return_value.agent_classifier_model = "gpt-4"
            mock_rsn_settings.return_value.agent_model = "gpt-4"
            mock_rsn_settings.return_value.agent_temperature = 0.1
            mock_rsn_settings.return_value.agent_max_tokens = 2000

            result = await graph.ainvoke(
                initial_state,
                {"configurable": {"openai_client": mock_openai_client}},
            )

        assert result["query_type"] == QueryType.LEGAL_SEARCH.value
        assert result["final_answer"] is not None


class TestComplianceCheckWithDrawing:
    """Test compliance check with drawing uploaded."""

    @pytest.mark.asyncio
    async def test_compliance_check_performs_calculations(
        self,
        mock_openai_client,
        mock_retriever_service,
        sample_drawing_context,
        sample_global_definitions,
    ):
        """Compliance check should calculate and return verdict."""
        graph = create_agent_graph(use_checkpointer=False)

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]

            if call_count[0] == 1:
                mock_response.choices[0].message.content = json.dumps({
                    "query_type": "COMPLIANCE_CHECK",
                    "intent": "check if extension complies with 50% rule",
                    "requires_drawing": True,
                    "confidence": "high",
                })
            else:
                mock_response.choices[0].message.content = (
                    "Based on your drawing and the 50% curtilage rule (Class A.1(b)):\n\n"
                    "**Status: COMPLIANT**\n\n"
                    "Your building coverage is 40% (80m² out of 200m²), which is "
                    "below the 50% maximum."
                )

            return mock_response

        mock_openai_client.chat.completions.create = mock_create

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="Is my extension compliant with the 50% rule?",
            drawing_context=sample_drawing_context,
        )

        with patch("app.agent.nodes.classifier.get_settings") as mock_cls, \
             patch("app.agent.nodes.reasoner.get_settings") as mock_rsn, \
             patch("app.agent.nodes.retriever.get_retriever_service", return_value=mock_retriever_service), \
             patch("app.agent.nodes.retriever.GLOBAL_DEFINITIONS", sample_global_definitions):

            mock_cls.return_value.agent_classifier_model = "gpt-4"
            mock_rsn.return_value.agent_model = "gpt-4"
            mock_rsn.return_value.agent_temperature = 0.1
            mock_rsn.return_value.agent_max_tokens = 2000

            result = await graph.ainvoke(
                initial_state,
                {"configurable": {"openai_client": mock_openai_client}},
            )

        assert result["query_type"] == QueryType.COMPLIANCE_CHECK.value
        assert len(result.get("calculation_results", [])) > 0
        assert result["final_answer"] is not None


class TestComplianceCheckWithoutDrawing:
    """Test compliance check when no drawing uploaded."""

    @pytest.mark.asyncio
    async def test_asks_for_drawing_upload(self, mock_openai_client):
        """Should ask for drawing when missing."""
        graph = create_agent_graph(use_checkpointer=False)

        async def mock_create(**kwargs):
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]
            mock_response.choices[0].message.content = json.dumps({
                "query_type": "COMPLIANCE_CHECK",
                "intent": "check compliance",
                "requires_drawing": True,
                "confidence": "high",
            })
            return mock_response

        mock_openai_client.chat.completions.create = mock_create

        empty_drawing = DrawingContext(session_id="test", has_drawing=False)

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="Is my extension compliant?",
            drawing_context=empty_drawing,
        )

        with patch("app.agent.nodes.classifier.get_settings") as mock_settings:
            mock_settings.return_value.agent_classifier_model = "gpt-4"

            result = await graph.ainvoke(
                initial_state,
                {"configurable": {"openai_client": mock_openai_client}},
            )

        assert MissingInfoType.DRAWING.value in result.get("missing_info", [])


class TestTemporalProblemDetection:
    """Test detection of the temporal problem (original dwellinghouse)."""

    @pytest.mark.asyncio
    async def test_detects_temporal_issue_and_asks_clarification(
        self,
        mock_openai_client,
        mock_retriever_service,
        sample_drawing_context_no_original,
        sample_retrieved_rule_50_percent,
        sample_global_definitions,
    ):
        """Should detect 'original dwellinghouse' and ask for clarification."""
        graph = create_agent_graph(use_checkpointer=False)

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]

            if call_count[0] == 1:
                mock_response.choices[0].message.content = json.dumps({
                    "query_type": "COMPLIANCE_CHECK",
                    "intent": "check 50% compliance",
                    "requires_drawing": True,
                    "confidence": "high",
                })
            else:
                mock_response.choices[0].message.content = (
                    "Before I can assess compliance, I need to know:\n\n"
                    "Is this the original house as built?"
                )

            return mock_response

        mock_openai_client.chat.completions.create = mock_create

        async def retriever_with_temporal(query, **kwargs):
            result = MagicMock()
            parent = MagicMock()
            parent.id = sample_retrieved_rule_50_percent["parent_id"]
            parent.parent_data = sample_retrieved_rule_50_percent
            parent.score = 0.9
            parent.is_xref_parent = False
            parent.resolved_xrefs = []

            context = MagicMock()
            context.text = sample_retrieved_rule_50_percent["text"]
            context.token_count = 100
            context.primary_parent_count = 1
            context.xref_parent_count = 0
            context.sections_included = ["A.1(b)"]

            result.context = context
            result.enhanced_parents = [parent]
            result.query_variations = [query]
            result.matched_children_count = 3
            result.ranked_parents = []

            return result

        mock_retriever_service.retrieve = retriever_with_temporal

        initial_state = create_initial_state(
            session_id="test-session",
            user_query="Does my extension comply with the 50% rule?",
            drawing_context=sample_drawing_context_no_original,
        )

        with patch("app.agent.nodes.classifier.get_settings") as mock_cls, \
             patch("app.agent.nodes.clarifier.get_settings") as mock_clr, \
             patch("app.agent.nodes.retriever.get_retriever_service", return_value=mock_retriever_service), \
             patch("app.agent.nodes.retriever.GLOBAL_DEFINITIONS", sample_global_definitions):

            mock_cls.return_value.agent_classifier_model = "gpt-4"
            mock_clr.return_value.agent_clarifier_model = "gpt-4"

            result = await graph.ainvoke(
                initial_state,
                {"configurable": {"openai_client": mock_openai_client}},
            )

        assert MissingInfoType.ORIGINAL_HOUSE.value in result.get("missing_info", [])
        assert result.get("awaiting_clarification", False) is True

        questions = result.get("clarification_questions", [])
        assert len(questions) > 0
        assert any(
            "original" in q.get("question", "").lower()
            for q in questions
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
        mock_retriever_service,
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
    async def test_orchestrator_maintains_conversation_state(self, mock_openai_client):
        """Orchestrator should maintain state across turns."""
        orchestrator = AgentOrchestrator(
            openai_client=mock_openai_client,
            redis_client=None,
        )

        call_count = [0]

        async def mock_create(**kwargs):
            call_count[0] += 1
            mock_response = MagicMock()
            mock_response.choices = [MagicMock()]

            if call_count[0] == 1:
                mock_response.choices[0].message.content = json.dumps({
                    "query_type": "GENERAL",
                    "intent": "understand PD",
                    "requires_drawing": False,
                    "confidence": "high",
                })
            else:
                mock_response.choices[0].message.content = (
                    "Permitted development allows certain works without planning permission."
                )

            return mock_response

        mock_openai_client.chat.completions.create = mock_create

        with patch("app.agent.nodes.classifier.get_settings") as mock_cls, \
             patch("app.agent.nodes.reasoner.get_settings") as mock_rsn, \
             patch("app.agent.orchestrator.get_settings") as mock_orch:

            mock_cls.return_value.agent_classifier_model = "gpt-4"
            mock_rsn.return_value.agent_model = "gpt-4"
            mock_rsn.return_value.agent_temperature = 0.1
            mock_rsn.return_value.agent_max_tokens = 2000
            mock_orch.return_value.openai_api_key = "test-key"

            await orchestrator.initialize()

            response = await orchestrator.process_query(
                session_id="test-session",
                query="What is permitted development?",
            )

        assert response.answer is not None
        assert response.query_type == "general"

        conversation = orchestrator.get_conversation("test-session")
        assert conversation is not None
        assert len(conversation.turns) == 2


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
