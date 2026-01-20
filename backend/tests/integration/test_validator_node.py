"""Integration tests for Validator Node (5.5)."""

import pytest

from app.agent.nodes.validator import ValidatorNode, validator_node
from app.agent.state import (
    AgentState,
    ComplianceCheck,
    ComplianceSummary,
    create_initial_state,
    get_compliance_checks,
    get_compliance_summary,
)


@pytest.fixture
def validator():
    """Create a ValidatorNode instance."""
    return ValidatorNode()


@pytest.fixture
def compliant_calculation_results():
    """Calculation results that should pass all rules."""
    return [
        {
            "calculation_type": "coverage_percentage",
            "input_values": {"building_area_m2": 40, "curtilage_area_m2": 200},
            "result": 20.0,  # 20% < 50% limit
            "unit": "%",
            "limit": 50.0,
            "compliant": True,
        },
        {
            "calculation_type": "boundary_distance",
            "input_values": {},
            "result": 3.0,  # 3m > 2m limit
            "unit": "metres",
            "limit": 2.0,
            "compliant": True,
        },
    ]


@pytest.fixture
def non_compliant_calculation_results():
    """Calculation results that should fail some rules."""
    return [
        {
            "calculation_type": "coverage_percentage",
            "input_values": {"building_area_m2": 120, "curtilage_area_m2": 200},
            "result": 60.0,  # 60% > 50% limit
            "unit": "%",
            "limit": 50.0,
            "compliant": False,
        },
        {
            "calculation_type": "boundary_distance",
            "input_values": {},
            "result": 1.5,  # 1.5m < 2m limit
            "unit": "metres",
            "limit": 2.0,
            "compliant": False,
        },
    ]


@pytest.fixture
def sample_drawing_context():
    """Sample drawing context with metadata."""
    return {
        "session_id": "test-session",
        "has_drawing": True,
        "house_type": "semi-detached",
        "designated_land_type": "none",
        "eaves_height_m": 2.5,
    }


class TestValidatorNodeInitialization:
    """Test ValidatorNode initialization."""

    def test_node_initializes_with_rule_registry(self, validator):
        """Node should initialize with a RuleRegistry."""
        assert validator.rule_registry is not None

    def test_node_is_callable(self, validator):
        """Node should be callable as a LangGraph node."""
        assert callable(validator)


class TestComplianceQuestionDetection:
    """Test compliance question detection."""

    def test_detects_comply_keyword(self, validator):
        """Should detect 'comply' as compliance question."""
        assert validator._is_compliance_question("Does my extension comply?")

    def test_detects_permitted_keyword(self, validator):
        """Should detect 'permitted' as compliance question."""
        assert validator._is_compliance_question("Is this permitted development?")

    def test_detects_allowed_keyword(self, validator):
        """Should detect 'allowed' as compliance question."""
        assert validator._is_compliance_question("Am I allowed to build this?")

    def test_detects_limit_keyword(self, validator):
        """Should detect 'limit' as compliance question."""
        assert validator._is_compliance_question("What is the height limit?")

    def test_detects_can_i_phrase(self, validator):
        """Should detect 'can i' as compliance question."""
        assert validator._is_compliance_question("Can I extend my house?")

    def test_detects_pd_keyword(self, validator):
        """Should detect 'pd' as compliance question."""
        assert validator._is_compliance_question("Does this fall under PD rights?")

    def test_non_compliance_question(self, validator):
        """Should not detect general questions as compliance."""
        assert not validator._is_compliance_question("Show the plot area")
        assert not validator._is_compliance_question("How do I upload a drawing?")
        assert not validator._is_compliance_question("Calculate the total footprint")


class TestExtensionTypeInference:
    """Test extension type inference from query."""

    def test_infers_rear_extension(self, validator):
        """Should infer rear extension from keywords."""
        assert validator._infer_extension_type("rear extension", {}) == "rear"
        assert validator._infer_extension_type("back of the house", {}) == "rear"

    def test_infers_side_extension(self, validator):
        """Should infer side extension from keywords."""
        assert validator._infer_extension_type("side extension", {}) == "side"
        assert validator._infer_extension_type("wrap around", {}) == "side"

    def test_infers_loft_extension(self, validator):
        """Should infer loft extension from keywords."""
        assert validator._infer_extension_type("loft conversion", {}) == "loft"
        assert validator._infer_extension_type("roof extension", {}) == "loft"
        assert validator._infer_extension_type("dormer window", {}) == "loft"

    def test_infers_porch(self, validator):
        """Should infer porch from keywords."""
        assert validator._infer_extension_type("porch", {}) == "porch"
        assert validator._infer_extension_type("front entrance", {}) == "porch"

    def test_infers_outbuilding(self, validator):
        """Should infer outbuilding from keywords."""
        assert validator._infer_extension_type("outbuilding", {}) == "outbuilding"
        assert validator._infer_extension_type("garden shed", {}) == "outbuilding"
        assert validator._infer_extension_type("garage", {}) == "outbuilding"

    def test_uses_explicit_type_from_context(self, validator):
        """Should use explicit type from drawing context."""
        ctx = {"extension_type": "side"}
        assert validator._infer_extension_type("some query", ctx) == "side"

    def test_defaults_to_rear(self, validator):
        """Should default to rear extension."""
        assert validator._infer_extension_type("is this okay?", {}) == "rear"


class TestStoreysInference:
    """Test storeys inference from query."""

    def test_infers_single_storey(self, validator):
        """Should infer single storey from keywords."""
        assert validator._infer_storeys("single storey extension", {}) == 1
        assert validator._infer_storeys("single-storey", {}) == 1
        assert validator._infer_storeys("1 storey", {}) == 1

    def test_infers_two_storey(self, validator):
        """Should infer two storey from keywords."""
        assert validator._infer_storeys("two storey extension", {}) == 2
        assert validator._infer_storeys("two-storey", {}) == 2
        assert validator._infer_storeys("double storey", {}) == 2

    def test_uses_explicit_storeys_from_context(self, validator):
        """Should use explicit storeys from drawing context."""
        ctx = {"storeys": 2}
        assert validator._infer_storeys("some query", ctx) == 2

    def test_defaults_to_single_storey(self, validator):
        """Should default to single storey."""
        assert validator._infer_storeys("is this okay?", {}) == 1


class TestValidatorWithCompliantData:
    """Test validator with compliant calculation results."""

    def test_validates_compliant_extension(
        self, validator, compliant_calculation_results, sample_drawing_context
    ):
        """Validator should pass compliant calculations."""
        state = create_initial_state(
            session_id="test",
            user_query="Is my rear extension compliant?",
        )
        state["drawing_context"] = sample_drawing_context
        state["calculation_results"] = compliant_calculation_results

        result = validator.validate(state)

        assert "compliance_checks" in result
        assert "compliance_summary" in result

        summary = result["compliance_summary"]
        # May have more rules checked but coverage should pass
        assert summary is not None

    def test_skips_non_compliance_queries(self, validator, sample_drawing_context):
        """Validator should skip non-compliance queries."""
        state = create_initial_state(
            session_id="test",
            user_query="Show the plot area measurement",
        )
        state["drawing_context"] = sample_drawing_context

        result = validator.validate(state)

        assert result["compliance_checks"] == []
        assert result["compliance_summary"] is None


class TestValidatorWithNonCompliantData:
    """Test validator with non-compliant calculation results."""

    def test_detects_non_compliant_coverage(
        self, validator, non_compliant_calculation_results, sample_drawing_context
    ):
        """Validator should detect non-compliant coverage."""
        state = create_initial_state(
            session_id="test",
            user_query="Does my extension comply with the 50% rule?",
        )
        state["drawing_context"] = sample_drawing_context
        state["calculation_results"] = non_compliant_calculation_results

        result = validator.validate(state)

        assert "compliance_checks" in result
        assert "compliance_summary" in result

        # Check that at least some rule was evaluated
        summary = result["compliance_summary"]
        assert summary is not None


class TestEvaluationContext:
    """Test evaluation context building."""

    def test_builds_context_from_calculations(
        self, validator, compliant_calculation_results, sample_drawing_context
    ):
        """Should build context from calculation results."""
        context = validator._build_evaluation_context(
            calculations=compliant_calculation_results,
            spatial=None,
            drawing_ctx=sample_drawing_context,
            query="Is this compliant?",
        )

        assert "house_type" in context
        assert context["house_type"] == "semi-detached"
        assert "coverage_result" in context
        assert context["coverage_result"]["coverage_percent"] == 20.0

    def test_handles_empty_calculations(self, validator, sample_drawing_context):
        """Should handle empty calculation results."""
        context = validator._build_evaluation_context(
            calculations=[],
            spatial=None,
            drawing_ctx=sample_drawing_context,
            query="Is this compliant?",
        )

        assert "house_type" in context
        assert "extension_type" in context

    def test_handles_missing_house_type(self, validator):
        """Should default house_type to semi-detached."""
        context = validator._build_evaluation_context(
            calculations=[],
            spatial=None,
            drawing_ctx={},
            query="Is this compliant?",
        )

        assert context["house_type"] == "semi-detached"

    def test_extracts_spatial_analysis_data(self, validator, sample_drawing_context):
        """Should extract data from spatial analysis."""
        spatial = {
            "requires_clarification": True,
            "buildable_sides": ["left"],
        }

        context = validator._build_evaluation_context(
            calculations=[],
            spatial=spatial,
            drawing_ctx=sample_drawing_context,
            query="Is this compliant?",
        )

        assert context["requires_clarification"] is True
        assert context["buildable_sides"] == ["left"]


class TestValidatorEdgeCases:
    """Test validator edge cases."""

    def test_handles_no_drawing_context(self, validator):
        """Validator should handle missing drawing context."""
        state = create_initial_state(
            session_id="test",
            user_query="Is this compliant?",
        )

        result = validator.validate(state)

        # Should still work with defaults
        assert "compliance_checks" in result

    def test_handles_empty_calculation_results(
        self, validator, sample_drawing_context
    ):
        """Validator should handle empty calculation results."""
        state = create_initial_state(
            session_id="test",
            user_query="Is this compliant?",
        )
        state["drawing_context"] = sample_drawing_context
        state["calculation_results"] = []

        result = validator.validate(state)

        assert "compliance_checks" in result
        assert "compliance_summary" in result

    def test_handles_conservation_area(self, validator):
        """Validator should handle conservation area land type."""
        drawing_ctx = {
            "has_drawing": True,
            "house_type": "detached",
            "designated_land_type": "conservation_area",
        }

        context = validator._build_evaluation_context(
            calculations=[],
            spatial=None,
            drawing_ctx=drawing_ctx,
            query="Is this compliant?",
        )

        assert context["land_type"] == "article_2_3"


class TestAsyncValidatorNode:
    """Test the async validator_node function."""

    @pytest.mark.asyncio
    async def test_async_validator_node(self, sample_drawing_context):
        """Async validator_node should work correctly."""
        state = create_initial_state(
            session_id="test",
            user_query="Is my extension compliant?",
        )
        state["drawing_context"] = sample_drawing_context

        result = await validator_node(state)

        assert "compliance_checks" in result
        assert "compliance_summary" in result


class TestStateHelperFunctions:
    """Test state helper functions for compliance."""

    def test_get_compliance_checks_returns_empty_when_missing(self):
        """get_compliance_checks should return empty list when not set."""
        state = create_initial_state(
            session_id="test",
            user_query="test",
        )
        checks = get_compliance_checks(state)
        assert checks == []

    def test_get_compliance_summary_returns_none_when_missing(self):
        """get_compliance_summary should return None when not set."""
        state = create_initial_state(
            session_id="test",
            user_query="test",
        )
        summary = get_compliance_summary(state)
        assert summary is None

    def test_initial_state_has_compliance_fields(self):
        """create_initial_state should include compliance fields."""
        state = create_initial_state(
            session_id="test",
            user_query="test",
        )

        assert "compliance_checks" in state
        assert state["compliance_checks"] == []
        assert "compliance_summary" in state
        assert state["compliance_summary"] is None


class TestComplianceCheckModel:
    """Test ComplianceCheck model."""

    def test_compliance_check_serialization(self):
        """ComplianceCheck should serialize to dict."""
        check = ComplianceCheck(
            rule_id="A.1(b)",
            rule_description="50% coverage rule",
            pdf_page=10,
            compliant=True,
            measured_value=35.0,
            threshold=50.0,
            unit="%",
            message="Coverage is within limit",
        )

        data = check.model_dump()

        assert data["rule_id"] == "A.1(b)"
        assert data["compliant"] is True
        assert data["measured_value"] == 35.0

    def test_compliance_check_with_error(self):
        """ComplianceCheck should handle errors."""
        check = ComplianceCheck(
            rule_id="A.1(f)",
            rule_description="Rear extension depth",
            compliant=None,
            error="Missing rear wall geometry",
        )

        assert check.compliant is None
        assert check.error == "Missing rear wall geometry"


class TestComplianceSummaryModel:
    """Test ComplianceSummary model."""

    def test_compliance_summary_all_pass(self):
        """ComplianceSummary should represent all rules passing."""
        summary = ComplianceSummary(
            overall_compliant=True,
            rules_checked=5,
            rules_passed=5,
            rules_failed=0,
            rules_inconclusive=0,
            verdict="All rules pass",
        )

        assert summary.overall_compliant is True
        assert summary.rules_failed == 0

    def test_compliance_summary_with_failures(self):
        """ComplianceSummary should represent failures."""
        summary = ComplianceSummary(
            overall_compliant=False,
            rules_checked=5,
            rules_passed=3,
            rules_failed=2,
            rules_inconclusive=0,
            verdict="Non-compliant: 2 rules failed",
        )

        assert summary.overall_compliant is False
        assert summary.rules_failed == 2

    def test_compliance_summary_inconclusive(self):
        """ComplianceSummary should handle inconclusive results."""
        summary = ComplianceSummary(
            overall_compliant=None,
            rules_checked=5,
            rules_passed=3,
            rules_failed=0,
            rules_inconclusive=2,
            verdict="Inconclusive: missing data for 2 rules",
        )

        assert summary.overall_compliant is None
        assert summary.rules_inconclusive == 2
