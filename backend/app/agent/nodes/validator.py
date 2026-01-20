"""Validator node for compliance rule checking.

Validates geometric calculations against UK Permitted Development rules
using the RuleRegistry from the geometry module.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.state import (
    AgentState,
    ComplianceCheck,
    ComplianceSummary,
    add_reasoning_step,
)
from app.geometry.rules import RuleRegistry
from app.geometry.types import HouseType, LandType

logger = logging.getLogger(__name__)


class ValidatorNode:
    """LangGraph node that validates calculations against regulatory rules.

    Receives:
    - calculation_results: Results from CalculatorNode
    - spatial_analysis: Semantic interpretation from CalculatorNode
    - drawing_context: Session metadata including house_type, land_type

    Outputs:
    - compliance_checks: List of individual rule check results
    - compliance_summary: Overall compliance verdict
    """

    COMPLIANCE_KEYWORDS = [
        "comply",
        "compliant",
        "compliance",
        "allowed",
        "permitted",
        "legal",
        "exceed",
        "limit",
        "within",
        "can i",
        "am i",
        "is my",
        "is it",
        "does it",
        "will it",
        "check",
        "valid",
        "rule",
        "regulation",
        "pd",
        "permitted development",
    ]

    def __init__(self):
        self.rule_registry = RuleRegistry()

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """Process state and perform compliance validation."""
        return self.validate(state)

    def validate(self, state: AgentState) -> dict[str, Any]:
        """Validate drawing against applicable regulatory rules.

        Args:
            state: Current agent state with calculation_results and spatial_analysis

        Returns:
            State updates with compliance_checks and compliance_summary
        """
        query = state.get("user_query", "").lower()
        calculation_results = state.get("calculation_results", [])
        spatial_analysis = state.get("spatial_analysis")
        drawing_ctx = state.get("drawing_context") or {}

        # Only run validation for compliance-related questions
        if not self._is_compliance_question(query):
            return {
                "compliance_checks": [],
                "compliance_summary": None,
                "reasoning_chain": add_reasoning_step(
                    state,
                    "Non-compliance query - skipping rule validation",
                ),
            }

        # Build evaluation context for rule checks
        context = self._build_evaluation_context(
            calculations=calculation_results,
            spatial=spatial_analysis,
            drawing_ctx=drawing_ctx,
            query=query,
        )

        # Evaluate all applicable rules
        try:
            evaluation = self.rule_registry.evaluate_all(context)
        except Exception as e:
            logger.error(f"Rule evaluation failed: {e}")
            return {
                "compliance_checks": [],
                "compliance_summary": None,
                "errors": state.get("errors", []) + [f"Rule evaluation failed: {e}"],
                "reasoning_chain": add_reasoning_step(
                    state,
                    f"Rule evaluation error: {e}",
                ),
            }

        # Convert results to ComplianceCheck objects
        checks = []
        for result in evaluation.get("results", []):
            check = ComplianceCheck(
                rule_id=result.get("rule_id", "unknown"),
                rule_description=result.get("rule_description", ""),
                pdf_page=result.get("pdf_page"),
                compliant=result.get("compliant"),
                measured_value=result.get("measured_value"),
                threshold=result.get("threshold"),
                unit=result.get("unit"),
                message=result.get("message", ""),
                error=result.get("error"),
            )
            checks.append(check.model_dump())

        # Build compliance summary
        summary = ComplianceSummary(
            overall_compliant=evaluation.get("overall_compliant"),
            rules_checked=evaluation.get("rules_checked", 0),
            rules_passed=evaluation.get("rules_passed", 0),
            rules_failed=evaluation.get("rules_failed", 0),
            rules_inconclusive=evaluation.get("rules_inconclusive", 0),
            verdict=evaluation.get("verdict", ""),
        )

        # Build reasoning message
        passed = summary.rules_passed
        failed = summary.rules_failed
        inconclusive = summary.rules_inconclusive
        total = summary.rules_checked

        if summary.overall_compliant is True:
            reasoning = f"Validated {total} rules: ALL PASS ({passed} compliant)"
        elif summary.overall_compliant is False:
            reasoning = f"Validated {total} rules: FAIL ({failed} non-compliant, {passed} passed)"
        else:
            reasoning = f"Validated {total} rules: {passed} passed, {failed} failed, {inconclusive} inconclusive"

        return {
            "compliance_checks": checks,
            "compliance_summary": summary.model_dump(),
            "reasoning_chain": add_reasoning_step(state, reasoning),
        }

    def _is_compliance_question(self, query: str) -> bool:
        """Check if the query is compliance-related."""
        query_lower = query.lower()
        return any(kw in query_lower for kw in self.COMPLIANCE_KEYWORDS)

    def _build_evaluation_context(
        self,
        calculations: list[dict],
        spatial: Optional[dict],
        drawing_ctx: dict,
        query: str,
    ) -> dict[str, Any]:
        """Build the context dict needed for rule evaluation.

        Args:
            calculations: List of calculation results from calculator node
            spatial: Spatial analysis results
            drawing_ctx: Drawing context with session metadata
            query: User query for extension type inference

        Returns:
            Context dict for rule evaluation
        """
        context: dict[str, Any] = {}

        # Extract house type with safe default
        house_type_str = drawing_ctx.get("house_type", "semi-detached")
        try:
            # Handle both string and enum values
            if hasattr(house_type_str, "value"):
                house_type_str = house_type_str.value
            context["house_type"] = house_type_str
        except (ValueError, AttributeError):
            context["house_type"] = "semi-detached"

        # Extract land type with safe default
        land_type_str = drawing_ctx.get("designated_land_type", "standard")
        try:
            if hasattr(land_type_str, "value"):
                land_type_str = land_type_str.value
            # Map designated land types to LandType enum values
            if land_type_str in ["conservation_area", "national_park", "aonb", "world_heritage", "broads"]:
                context["land_type"] = LandType.ARTICLE_2_3.value
            else:
                context["land_type"] = "standard"
        except (ValueError, AttributeError):
            context["land_type"] = "standard"

        # Extract values from calculation results
        for calc in calculations:
            calc_type = calc.get("calculation_type", "")

            if calc_type == "coverage_percentage":
                context["coverage_result"] = {
                    "coverage_percent": calc.get("result", 0),
                    "compliant_50_percent": calc.get("compliant", True),
                }

            elif calc_type == "boundary_distance":
                context["distance_to_boundary"] = calc.get("result", 0)

            elif calc_type == "extension_depth":
                context["extension_depth_m"] = calc.get("result", 0)

            elif calc_type == "height_check":
                context["eaves_height"] = calc.get("result", 0)

            elif calc_type == "width":
                context["original_width_m"] = calc.get("result", 0)

            elif calc_type == "max_side_extension_width":
                if "width_result" not in context:
                    context["width_result"] = {}
                context["width_result"]["half_original_width_m"] = calc.get("result", 0)

        # Add height from drawing context if not from calculations
        if "eaves_height" not in context:
            eaves = drawing_ctx.get("eaves_height_m")
            if eaves:
                context["eaves_height"] = eaves

        # Add extension height
        extension_height = drawing_ctx.get("building_height_m")
        if extension_height:
            context["extension_height"] = extension_height

        # Determine extension type from query or default
        context["extension_type"] = self._infer_extension_type(query, drawing_ctx)

        # Determine storeys from query or default
        context["storeys"] = self._infer_storeys(query, drawing_ctx)

        # Add spatial analysis data
        if spatial:
            context["requires_clarification"] = spatial.get("requires_clarification", False)
            context["buildable_sides"] = spatial.get("buildable_sides", ["left", "right"])

        # Add any explicit metadata
        context["neighbour_consultation"] = drawing_ctx.get("neighbour_consultation", False)

        return context

    def _infer_extension_type(self, query: str, drawing_ctx: dict) -> str:
        """Infer extension type from query keywords or drawing context."""
        query_lower = query.lower()

        # Check explicit metadata first
        explicit_type = drawing_ctx.get("extension_type")
        if explicit_type:
            return explicit_type

        # Infer from query keywords
        if any(kw in query_lower for kw in ["rear", "back"]):
            return "rear"
        elif any(kw in query_lower for kw in ["side", "wrap"]):
            return "side"
        elif any(kw in query_lower for kw in ["loft", "roof", "dormer"]):
            return "loft"
        elif any(kw in query_lower for kw in ["porch", "front"]):
            return "porch"
        elif any(kw in query_lower for kw in ["outbuilding", "garage", "shed", "garden"]):
            return "outbuilding"

        # Default to rear extension (most common)
        return "rear"

    def _infer_storeys(self, query: str, drawing_ctx: dict) -> int:
        """Infer number of storeys from query keywords or drawing context."""
        query_lower = query.lower()

        # Check explicit metadata first
        explicit_storeys = drawing_ctx.get("storeys")
        if explicit_storeys:
            return explicit_storeys

        # Infer from query keywords
        if any(kw in query_lower for kw in ["two storey", "two-storey", "2 storey", "double storey", "multi"]):
            return 2
        elif any(kw in query_lower for kw in ["single storey", "single-storey", "1 storey", "one storey"]):
            return 1

        # Default to single storey
        return 1


# Module-level instance for use as a node
_validator = ValidatorNode()


async def validator_node(state: AgentState) -> dict[str, Any]:
    """Async wrapper for ValidatorNode.

    This is the LangGraph node entry point that performs compliance validation.

    Args:
        state: Current agent state with calculation_results and spatial_analysis

    Returns:
        State updates with compliance_checks and compliance_summary
    """
    return _validator.validate(state)
