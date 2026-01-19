"""Pytest fixtures for agent testing."""

import json
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.state import (
    AgentState,
    Assumption,
    AssumptionSource,
    CalculationResult,
    ClarificationQuestion,
    ConfidenceLevel,
    DrawingContext,
    MissingInfoType,
    QueryType,
    RetrievedRule,
    create_initial_state,
)


@pytest.fixture
def sample_drawing_context() -> DrawingContext:
    """Drawing context with typical measurements."""
    return DrawingContext(
        session_id="test-session-123",
        has_drawing=True,
        plot_area_sqm=200.0,
        building_footprint_sqm=80.0,
        building_height_m=5.0,
        eaves_height_m=3.0,
        distance_to_boundary_m=3.0,
        distance_to_rear_boundary_m=10.0,
        house_type="detached",
        is_original_house=True,
        designated_land_type="none",
        layers_present=["Plot Boundary", "External Walls", "Proposed Extension"],
    )


@pytest.fixture
def sample_drawing_context_no_original() -> DrawingContext:
    """Drawing context where is_original_house is unknown (temporal problem)."""
    return DrawingContext(
        session_id="test-session-456",
        has_drawing=True,
        plot_area_sqm=200.0,
        building_footprint_sqm=100.0,
        building_height_m=5.0,
        distance_to_boundary_m=2.5,
        house_type="detached",
        is_original_house=None,
        designated_land_type=None,
        layers_present=["Plot Boundary", "External Walls"],
    )


@pytest.fixture
def sample_drawing_context_empty() -> DrawingContext:
    """Empty drawing context (no drawing uploaded)."""
    return DrawingContext(
        session_id="test-session-789",
        has_drawing=False,
    )


@pytest.fixture
def sample_retrieved_rule_50_percent() -> dict:
    """Retrieved rule for 50% curtilage coverage."""
    return {
        "parent_id": "rule-50-percent",
        "text": (
            "Development is not permitted by Class A if the total area of ground "
            "covered by buildings within the curtilage of the dwellinghouse "
            "(other than the original dwellinghouse) would exceed 50% of the total "
            "area of the curtilage (excluding the ground area of the original dwellinghouse)."
        ),
        "section": "A.1(b)",
        "page_start": 7,
        "page_end": 8,
        "source": "GPDO",
        "relevance_score": 0.92,
        "uses_definitions": ["original dwellinghouse", "curtilage"],
        "xrefs": [],
        "sections_covered": ["A.1(b)"],
        "has_exceptions": False,
        "designated_land_specific": False,
    }


@pytest.fixture
def sample_retrieved_rule_height() -> dict:
    """Retrieved rule for height limits."""
    return {
        "parent_id": "rule-height",
        "text": (
            "Development is not permitted by Class A if the height of the eaves "
            "of the enlarged part would exceed 3 metres where the enlarged part "
            "is within 2 metres of any boundary of the curtilage."
        ),
        "section": "A.1(i)",
        "page_start": 9,
        "page_end": 9,
        "source": "GPDO",
        "relevance_score": 0.88,
        "uses_definitions": [],
        "xrefs": [],
        "sections_covered": ["A.1(i)"],
        "has_exceptions": False,
        "designated_land_specific": False,
    }


@pytest.fixture
def sample_retrieved_rule_designated() -> dict:
    """Retrieved rule for designated land (Article 2(3))."""
    return {
        "parent_id": "rule-designated",
        "text": (
            "On article 2(3) land, development is not permitted by Class A if "
            "the enlarged part of the dwellinghouse would consist of or include "
            "the cladding of any part of the exterior."
        ),
        "section": "A.2(a)",
        "page_start": 12,
        "page_end": 12,
        "source": "GPDO",
        "relevance_score": 0.85,
        "uses_definitions": [],
        "xrefs": [],
        "sections_covered": ["A.2(a)"],
        "has_exceptions": False,
        "designated_land_specific": True,
    }


@pytest.fixture
def sample_global_definitions() -> dict[str, str]:
    """Global definitions from legislation."""
    return {
        "original dwellinghouse": (
            "The house as it was first built, or as it stood on 1st July 1948 "
            "(whichever is later). Any extensions built after that date are not "
            "considered part of the original house for calculating limits."
        ),
        "curtilage": (
            "The area of land around a house that is used for the enjoyment of the "
            "dwelling. This typically includes gardens, driveways, and outbuildings."
        ),
    }


@pytest.fixture
def initial_state_general_query() -> AgentState:
    """Initial state for a general query."""
    return create_initial_state(
        session_id="test-session",
        user_query="What is permitted development?",
    )


@pytest.fixture
def initial_state_compliance_query(sample_drawing_context) -> AgentState:
    """Initial state for a compliance query with drawing."""
    return create_initial_state(
        session_id="test-session-123",
        user_query="Is my extension compliant with the 50% rule?",
        drawing_context=sample_drawing_context,
    )


@pytest.fixture
def initial_state_compliance_no_drawing() -> AgentState:
    """Initial state for compliance query without drawing."""
    return create_initial_state(
        session_id="test-session-no-drawing",
        user_query="Is my extension compliant?",
    )


@pytest.fixture
def mock_openai_client():
    """Mock OpenAI client for testing."""
    client = AsyncMock()

    async def mock_create(**kwargs):
        messages = kwargs.get("messages", [])
        user_content = ""
        for msg in messages:
            if msg.get("role") == "user":
                user_content = msg.get("content", "")
                break

        if "classify" in user_content.lower() or "categories" in user_content.lower():
            response_content = json.dumps({
                "query_type": "GENERAL",
                "intent": "understand permitted development",
                "requires_drawing": False,
                "confidence": "high",
            })
        elif "clarify" in user_content.lower() or "clarification" in user_content.lower():
            response_content = (
                "Before I can help you, I need some additional information:\n\n"
                "1. Is this the original house as built, or has it been extended before?"
            )
        else:
            response_content = (
                "Based on the regulations provided, here is my assessment:\n\n"
                "**Answer:** Permitted development allows certain building works "
                "without full planning permission.\n\n"
                "**Legal Basis:** Class A of the GPDO.\n\n"
                "*Confidence: High*"
            )

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_content
        return mock_response

    client.chat.completions.create = mock_create
    return client


@pytest.fixture
def mock_openai_classifier_compliance():
    """Mock OpenAI that classifies as compliance check."""
    client = AsyncMock()

    async def mock_create(**kwargs):
        response_content = json.dumps({
            "query_type": "COMPLIANCE_CHECK",
            "intent": "check if extension complies with 50% rule",
            "requires_drawing": True,
            "confidence": "high",
        })

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = response_content
        return mock_response

    client.chat.completions.create = mock_create
    return client


@pytest.fixture
def mock_retriever_service(
    sample_retrieved_rule_50_percent,
    sample_retrieved_rule_height,
):
    """Mock retriever service returning sample rules."""
    from app.services.retrieval.retriever import RetrievalResult
    from app.services.retrieval.context_assembler import AssembledContext
    from app.services.retrieval.xref_resolver import EnhancedParent

    service = AsyncMock()

    async def mock_retrieve(query, **kwargs):
        enhanced_parents = []

        if "50%" in query or "curtilage" in query.lower() or "compliant" in query.lower():
            parent = MagicMock()
            parent.id = sample_retrieved_rule_50_percent["parent_id"]
            parent.parent_data = sample_retrieved_rule_50_percent
            parent.score = sample_retrieved_rule_50_percent["relevance_score"]
            parent.is_xref_parent = False
            parent.resolved_xrefs = []
            enhanced_parents.append(parent)

        if "height" in query.lower():
            parent = MagicMock()
            parent.id = sample_retrieved_rule_height["parent_id"]
            parent.parent_data = sample_retrieved_rule_height
            parent.score = sample_retrieved_rule_height["relevance_score"]
            parent.is_xref_parent = False
            parent.resolved_xrefs = []
            enhanced_parents.append(parent)

        context_text = "\n\n".join([
            p.parent_data.get("text", "") for p in enhanced_parents
        ])

        context = MagicMock()
        context.text = context_text
        context.token_count = len(context_text.split())
        context.primary_parent_count = len(enhanced_parents)
        context.xref_parent_count = 0
        context.sections_included = [
            p.parent_data.get("section") for p in enhanced_parents
        ]

        result = MagicMock()
        result.context = context
        result.query_variations = [query]
        result.matched_children_count = len(enhanced_parents) * 3
        result.ranked_parents = []
        result.enhanced_parents = enhanced_parents

        return result

    service.retrieve = mock_retrieve
    service.initialize = AsyncMock()
    return service


@pytest.fixture
def mock_redis_client():
    """Mock Redis client for session testing."""
    client = AsyncMock()

    storage = {}

    async def mock_get(key):
        return storage.get(key)

    async def mock_set(key, value, **kwargs):
        storage[key] = value

    async def mock_delete(key):
        if key in storage:
            del storage[key]

    client.get = mock_get
    client.set = mock_set
    client.delete = mock_delete

    return client


@pytest.fixture
def mock_session_with_drawing(sample_drawing_context):
    """Mock session repository that returns a session with drawing."""
    from app.repositories.session_repository import SessionRepository

    repo = AsyncMock(spec=SessionRepository)

    async def mock_get_meta(session_id):
        return {
            "session_id": session_id,
            "user_id": "test-user",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def mock_get_context(session_id):
        return {
            "objects": [
                {
                    "type": "POLYLINE",
                    "layer": "Plot Boundary",
                    "closed": True,
                    "points": [[0, 0], [20000, 0], [20000, 10000], [0, 10000]],
                },
                {
                    "type": "POLYLINE",
                    "layer": "External Walls",
                    "closed": True,
                    "points": [[2000, 2000], [10000, 2000], [10000, 10000], [2000, 10000]],
                },
            ],
            "metadata": {
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
                "object_count": 2,
                "coordinate_unit": "mm",
                "context_version": 1,
                "layers_present": ["Plot Boundary", "External Walls"],
                "layer_counts": {"Plot Boundary": 1, "External Walls": 1},
                "has_plot_boundary": True,
                "plot_boundary_closed": True,
                "bounding_box": {
                    "min_x": 0,
                    "min_y": 0,
                    "max_x": 20000,
                    "max_y": 10000,
                },
            },
        }

    repo.get_meta = mock_get_meta
    repo.get_context = mock_get_context

    return repo


@pytest.fixture
def mock_session_empty():
    """Mock session repository with no drawing."""
    from app.repositories.session_repository import SessionRepository

    repo = AsyncMock(spec=SessionRepository)

    async def mock_get_meta(session_id):
        return {
            "session_id": session_id,
            "user_id": "test-user",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    async def mock_get_context(session_id):
        return None

    repo.get_meta = mock_get_meta
    repo.get_context = mock_get_context

    return repo
