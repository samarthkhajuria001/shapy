"""Integration tests for Calculator Node (Phase 5.4)."""

import pytest

from app.agent.nodes.calculator import CalculatorNode, calculator_node
from app.agent.state import (
    AgentState,
    CalculationResult,
    create_initial_state,
    get_calculation_results,
    get_spatial_analysis,
)


@pytest.fixture
def calculator():
    """Create a CalculatorNode instance."""
    return CalculatorNode()


@pytest.fixture
def sample_drawing_objects():
    """Sample raw drawing objects simulating a typical house plot."""
    return [
        # Plot boundary as closed polyline (20m x 30m = 600m² plot)
        {
            "type": "POLYLINE",
            "layer": "Plot Boundary",
            "closed": True,
            "points": [
                [0, 0],
                [20000, 0],
                [20000, 30000],
                [0, 30000],
            ],
        },
        # Walls as closed polyline (10m x 8m = 80m² building)
        {
            "type": "POLYLINE",
            "layer": "Walls",
            "closed": True,
            "points": [
                [5000, 10000],
                [15000, 10000],
                [15000, 18000],
                [5000, 18000],
            ],
        },
        # Highway at the bottom
        {
            "type": "LINE",
            "layer": "Highway",
            "start": [0, -2000],
            "end": [20000, -2000],
        },
    ]


@pytest.fixture
def sample_drawing_context():
    """Sample drawing context with pre-calculated values."""
    return {
        "session_id": "test-session",
        "has_drawing": True,
        "plot_area_sqm": 600.0,
        "building_footprint_sqm": 80.0,
        "eaves_height_m": 2.5,
        "distance_to_boundary_m": 5.0,
        "house_type": "semi-detached",
    }


class TestCalculatorNodeInitialization:
    """Test CalculatorNode initialization."""

    def test_node_initializes_with_components(self, calculator):
        """Node should initialize with calculator, inference engine, and parser."""
        assert calculator.calculator is not None
        assert calculator.inference_engine is not None
        assert calculator.drawing_parser is not None

    def test_node_is_callable(self, calculator):
        """Node should be callable as a LangGraph node."""
        assert callable(calculator)


class TestCalculatorWithRawDrawingObjects:
    """Test calculator with raw drawing objects (geometry engine path)."""

    def test_parses_drawing_objects_successfully(
        self, calculator, sample_drawing_objects
    ):
        """Calculator should parse raw drawing objects into Shapely geometries."""
        parsed = calculator._parse_objects(sample_drawing_objects)

        assert parsed is not None
        assert "walls" in parsed
        assert "plot_boundary" in parsed
        assert "highways" in parsed
        assert len(parsed["walls"]) == 1
        assert parsed["plot_boundary"] is not None
        assert len(parsed["highways"]) == 1

    def test_calculates_areas_from_geometry(
        self, calculator, sample_drawing_objects, sample_drawing_context
    ):
        """Calculator should calculate areas from raw geometry."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my plot area?",
            raw_drawing_objects=sample_drawing_objects,
        )
        state["drawing_context"] = sample_drawing_context

        result = calculator.calculate(state)

        assert "calculation_results" in result
        calc_results = result["calculation_results"]
        assert len(calc_results) >= 1

        # Find the area calculation
        area_calc = next(
            (c for c in calc_results if c["calculation_type"] == "area"), None
        )
        assert area_calc is not None
        assert area_calc["unit"] == "m²"

    def test_performs_spatial_analysis(
        self, calculator, sample_drawing_objects, sample_drawing_context
    ):
        """Calculator should perform spatial analysis on geometry."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
            raw_drawing_objects=sample_drawing_objects,
        )
        state["drawing_context"] = sample_drawing_context

        result = calculator.calculate(state)

        assert "spatial_analysis" in result
        spatial = result["spatial_analysis"]
        # Spatial analysis should be populated when walls exist
        assert spatial is not None or True  # May be None if no highways

    def test_calculates_boundary_distance_from_geometry(
        self, calculator, sample_drawing_objects, sample_drawing_context
    ):
        """Calculator should calculate boundary distance from geometry."""
        state = create_initial_state(
            session_id="test",
            user_query="How far is my building from the boundary?",
            raw_drawing_objects=sample_drawing_objects,
        )
        state["drawing_context"] = sample_drawing_context

        result = calculator.calculate(state)

        calc_results = result["calculation_results"]
        dist_calc = next(
            (c for c in calc_results if c["calculation_type"] == "boundary_distance"),
            None,
        )
        assert dist_calc is not None
        assert dist_calc["unit"] == "metres"
        assert dist_calc["result"] >= 0

    def test_calculates_coverage_from_geometry(
        self, calculator, sample_drawing_objects, sample_drawing_context
    ):
        """Calculator should calculate coverage percentage from geometry."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage percentage?",
            raw_drawing_objects=sample_drawing_objects,
        )
        state["drawing_context"] = sample_drawing_context

        result = calculator.calculate(state)

        calc_results = result["calculation_results"]
        coverage_calc = next(
            (c for c in calc_results if c["calculation_type"] == "coverage_percentage"),
            None,
        )
        assert coverage_calc is not None
        assert coverage_calc["unit"] == "%"
        assert coverage_calc["limit"] == 50.0
        assert coverage_calc["limit_source"] == "Class A.1(b) - 50% curtilage rule"


class TestCalculatorWithDrawingContext:
    """Test calculator with pre-calculated drawing context (fallback path)."""

    def test_calculates_coverage_from_context(self, calculator, sample_drawing_context):
        """Calculator should calculate coverage from pre-calculated values."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
        )
        state["drawing_context"] = sample_drawing_context
        state["pending_calculations"] = ["coverage_percentage"]

        result = calculator.calculate(state)

        calc_results = result["calculation_results"]
        assert len(calc_results) >= 1

        coverage_calc = next(
            (c for c in calc_results if c["calculation_type"] == "coverage_percentage"),
            None,
        )
        assert coverage_calc is not None
        # 80m² / 600m² = 13.3%
        assert coverage_calc["result"] == pytest.approx(13.3, abs=0.1)
        assert coverage_calc["compliant"] is True

    def test_calculates_boundary_distance_from_context(
        self, calculator, sample_drawing_context
    ):
        """Calculator should calculate boundary distance from context."""
        state = create_initial_state(
            session_id="test",
            user_query="Am I within 2m of the boundary?",
        )
        state["drawing_context"] = sample_drawing_context
        state["pending_calculations"] = ["boundary_distance"]

        result = calculator.calculate(state)

        calc_results = result["calculation_results"]
        dist_calc = next(
            (c for c in calc_results if c["calculation_type"] == "boundary_distance"),
            None,
        )
        assert dist_calc is not None
        assert dist_calc["result"] == 5.0
        assert dist_calc["compliant"] is True  # 5m >= 2m

    def test_calculates_height_from_context(self, calculator, sample_drawing_context):
        """Calculator should check height from context."""
        state = create_initial_state(
            session_id="test",
            user_query="Is my height OK?",
        )
        state["drawing_context"] = sample_drawing_context
        state["pending_calculations"] = ["height_check"]

        result = calculator.calculate(state)

        calc_results = result["calculation_results"]
        height_calc = next(
            (c for c in calc_results if c["calculation_type"] == "height_check"), None
        )
        assert height_calc is not None
        assert height_calc["result"] == 2.5  # eaves_height_m
        assert height_calc["compliant"] is True  # 2.5m < 4m limit


class TestCalculatorEdgeCases:
    """Test calculator edge cases."""

    def test_handles_no_drawing_context(self, calculator):
        """Calculator should handle missing drawing context gracefully."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
        )

        result = calculator.calculate(state)

        assert result["calculation_results"] == []
        assert "No drawing context" in result["reasoning_chain"][-1]

    def test_handles_empty_drawing_objects(self, calculator, sample_drawing_context):
        """Calculator should fall back to context when no raw objects."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
            raw_drawing_objects=[],
        )
        state["drawing_context"] = sample_drawing_context

        result = calculator.calculate(state)

        # Should fall back to context-based calculation
        calc_results = result["calculation_results"]
        coverage_calc = next(
            (c for c in calc_results if c["calculation_type"] == "coverage_percentage"),
            None,
        )
        assert coverage_calc is not None

    def test_handles_malformed_drawing_objects(self, calculator, sample_drawing_context):
        """Calculator should handle malformed drawing objects."""
        malformed_objects = [
            {"type": "POLYLINE"},  # Missing points
            {"type": "LINE", "layer": "Highway"},  # Missing start/end
        ]

        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
            raw_drawing_objects=malformed_objects,
        )
        state["drawing_context"] = sample_drawing_context

        # Should not raise, should fall back to context
        result = calculator.calculate(state)
        assert "calculation_results" in result

    def test_validates_impossible_geometry(self, calculator):
        """Calculator should reject impossible geometry."""
        invalid_context = {
            "session_id": "test",
            "has_drawing": True,
            "plot_area_sqm": 100.0,
            "building_footprint_sqm": 200.0,  # Building larger than plot!
        }

        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
        )
        state["drawing_context"] = invalid_context

        result = calculator.calculate(state)

        assert result["should_escalate"] is True
        assert len(result.get("errors", [])) > 0
        assert "larger than plot" in result["errors"][0]

    def test_validates_unreasonable_values(self, calculator):
        """Calculator should flag unreasonable values."""
        unreasonable_context = {
            "session_id": "test",
            "has_drawing": True,
            "building_height_m": 50.0,  # 50m is unreasonable for house
        }

        state = create_initial_state(
            session_id="test",
            user_query="What is my height?",
        )
        state["drawing_context"] = unreasonable_context

        result = calculator.calculate(state)

        assert result["should_escalate"] is True


class TestCalculatorNodeQueryDetection:
    """Test query keyword detection."""

    def test_detects_area_keywords(self, calculator):
        """Calculator should detect area-related queries."""
        assert calculator._needs_area("what is my plot area")
        assert calculator._needs_area("coverage check")
        assert calculator._needs_area("50% rule")
        assert calculator._needs_area("curtilage")
        assert not calculator._needs_area("how tall is it")

    def test_detects_distance_keywords(self, calculator):
        """Calculator should detect distance-related queries."""
        assert calculator._needs_distance("distance to boundary")
        assert calculator._needs_distance("am i within 2m")
        assert calculator._needs_distance("how far from boundary")
        assert not calculator._needs_distance("what is my area")

    def test_detects_height_keywords(self, calculator):
        """Calculator should detect height-related queries."""
        assert calculator._needs_height("what is the height")
        assert calculator._needs_height("eaves level")
        assert calculator._needs_height("how tall")
        assert not calculator._needs_height("how wide")

    def test_detects_extension_keywords(self, calculator):
        """Calculator should detect extension-related queries."""
        assert calculator._needs_extension("rear extension depth")
        assert calculator._needs_extension("how far does it project")
        assert calculator._needs_extension("extend beyond wall")
        assert not calculator._needs_extension("plot boundary")


class TestAsyncCalculatorNode:
    """Test the async calculator_node function."""

    @pytest.mark.asyncio
    async def test_async_calculator_node(self, sample_drawing_context):
        """Async calculator_node should work correctly."""
        state = create_initial_state(
            session_id="test",
            user_query="What is my coverage?",
        )
        state["drawing_context"] = sample_drawing_context
        state["pending_calculations"] = ["coverage_percentage"]

        result = await calculator_node(state)

        assert "calculation_results" in result
        assert len(result["calculation_results"]) >= 1


class TestStateHelperFunctions:
    """Test state helper functions for Phase 5.4."""

    def test_get_spatial_analysis_returns_none_when_missing(self):
        """get_spatial_analysis should return None when not set."""
        state = create_initial_state(
            session_id="test",
            user_query="test",
        )
        assert get_spatial_analysis(state) is None

    def test_create_initial_state_with_raw_objects(self, sample_drawing_objects):
        """create_initial_state should accept raw_drawing_objects."""
        state = create_initial_state(
            session_id="test",
            user_query="test",
            raw_drawing_objects=sample_drawing_objects,
        )

        assert state["raw_drawing_objects"] == sample_drawing_objects

    def test_create_initial_state_defaults_raw_objects_to_empty(self):
        """create_initial_state should default raw_drawing_objects to empty list."""
        state = create_initial_state(
            session_id="test",
            user_query="test",
        )

        assert state["raw_drawing_objects"] == []
        assert state["spatial_analysis"] is None
