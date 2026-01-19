"""Calculator node for geometric calculations.

This is a stub implementation that performs basic calculations using
data from DrawingContext. Phase 5 will provide a full Shapely-based
geometric calculator with precise measurements.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agent.state import (
    AgentState,
    CalculationResult,
    add_reasoning_step,
)

logger = logging.getLogger(__name__)


SANITY_LIMITS = {
    "plot_area_sqm": (10.0, 10000.0),
    "building_footprint_sqm": (5.0, 5000.0),
    "building_height_m": (1.0, 20.0),
    "eaves_height_m": (1.0, 15.0),
    "distance_to_boundary_m": (0.0, 100.0),
}


def _validate_geometry(drawing_ctx: dict) -> list[str]:
    """Check for impossible geometry that would indicate data issues."""
    errors: list[str] = []

    plot_area = drawing_ctx.get("plot_area_sqm")
    building_footprint = drawing_ctx.get("building_footprint_sqm")

    if plot_area and building_footprint:
        if building_footprint > plot_area:
            errors.append(
                "Building footprint appears larger than plot area. "
                "Please check your drawing measurements."
            )

    for field, (min_val, max_val) in SANITY_LIMITS.items():
        value = drawing_ctx.get(field)
        if value is not None:
            if value < min_val or value > max_val:
                errors.append(
                    f"Unusual {field.replace('_', ' ')}: {value}. "
                    f"Expected range: {min_val}-{max_val}."
                )

    return errors


def _calculate_coverage_percentage(
    drawing_ctx: dict,
    prior_extensions_sqm: float = 0.0,
) -> CalculationResult | None:
    """Calculate building coverage as percentage of plot."""
    plot_area = drawing_ctx.get("plot_area_sqm")
    building_footprint = drawing_ctx.get("building_footprint_sqm")

    if not plot_area or not building_footprint:
        return None

    total_footprint = building_footprint + prior_extensions_sqm
    percentage = (building_footprint / plot_area) * 100

    compliant = percentage <= 50.0
    margin = 50.0 - percentage

    notes = None
    if prior_extensions_sqm > 0:
        notes = f"Includes {prior_extensions_sqm}m2 of prior extensions"

    return CalculationResult(
        calculation_type="coverage_percentage",
        input_values={
            "building_footprint_sqm": building_footprint,
            "plot_area_sqm": plot_area,
            "prior_extensions_sqm": prior_extensions_sqm,
        },
        result=round(percentage, 1),
        unit="%",
        limit=50.0,
        limit_source="Class A.1(b) - 50% curtilage rule",
        compliant=compliant,
        margin=round(margin, 1),
        notes=notes,
    )


def _calculate_boundary_distance(
    drawing_ctx: dict,
) -> CalculationResult | None:
    """Check distance to boundary against 2m rule."""
    distance = drawing_ctx.get("distance_to_boundary_m")

    if distance is None:
        return None

    compliant = distance >= 2.0
    margin = distance - 2.0

    notes = None
    if not compliant:
        notes = "Within 2m of boundary - eaves height limited to 3m"

    return CalculationResult(
        calculation_type="boundary_distance",
        input_values={"distance_to_boundary_m": distance},
        result=round(distance, 2),
        unit="metres",
        limit=2.0,
        limit_source="Class A.1(i) - 2m boundary rule",
        compliant=compliant,
        margin=round(margin, 2),
        notes=notes,
    )


def _calculate_height_check(
    drawing_ctx: dict,
) -> CalculationResult | None:
    """Check building height against limits."""
    building_height = drawing_ctx.get("building_height_m")
    eaves_height = drawing_ctx.get("eaves_height_m")
    distance_to_boundary = drawing_ctx.get("distance_to_boundary_m")

    if eaves_height is None and building_height is None:
        return None

    check_height = eaves_height if eaves_height else building_height
    if check_height is None:
        return None

    if distance_to_boundary and distance_to_boundary < 2.0:
        limit = 3.0
        limit_source = "Class A.1(i) - eaves within 2m of boundary"
    else:
        limit = 4.0
        limit_source = "Class A.1(ja) - single storey max height"

    compliant = check_height <= limit
    margin = limit - check_height

    height_type = "eaves" if eaves_height else "building"

    return CalculationResult(
        calculation_type="height_check",
        input_values={
            f"{height_type}_height_m": check_height,
            "distance_to_boundary_m": distance_to_boundary,
        },
        result=round(check_height, 2),
        unit="metres",
        limit=limit,
        limit_source=limit_source,
        compliant=compliant,
        margin=round(margin, 2),
        notes=f"Checked {height_type} height" if height_type else None,
    )


def _calculate_extension_depth(
    drawing_ctx: dict,
    house_type: str | None = None,
) -> CalculationResult | None:
    """
    Stub for extension depth calculation.

    Phase 5 will calculate actual extension depth from geometry.
    For now, we just return None as we don't have the geometry parsing.
    """
    return None


async def calculator_node(state: AgentState) -> dict[str, Any]:
    """
    Perform geometric calculations on drawing data.

    This stub implementation uses pre-calculated values from DrawingContext.
    Phase 5 will provide precise Shapely-based calculations from raw geometry.

    Args:
        state: Current agent state with drawing_context and pending_calculations

    Returns:
        State updates with calculation_results
    """
    drawing_ctx = state.get("drawing_context")
    pending = state.get("pending_calculations", [])

    if not drawing_ctx or not drawing_ctx.get("has_drawing"):
        return {
            "calculation_results": [],
            "pending_calculations": [],
            "reasoning_chain": add_reasoning_step(
                state,
                "No drawing context for calculations",
            ),
        }

    geometry_errors = _validate_geometry(drawing_ctx)
    if geometry_errors:
        logger.warning(f"Geometry validation errors: {geometry_errors}")
        return {
            "calculation_results": [],
            "pending_calculations": [],
            "errors": state.get("errors", []) + geometry_errors,
            "should_escalate": True,
            "reasoning_chain": add_reasoning_step(
                state,
                f"Geometry validation failed: {len(geometry_errors)} issues",
            ),
        }

    results: list[dict] = []
    prior_extensions = drawing_ctx.get("prior_extensions_sqm", 0.0) or 0.0
    house_type = drawing_ctx.get("house_type")

    if "coverage_percentage" in pending:
        calc = _calculate_coverage_percentage(drawing_ctx, prior_extensions)
        if calc:
            results.append(calc.model_dump())
            logger.debug(f"Coverage: {calc.result}% (limit 50%)")

    if "boundary_distance" in pending:
        calc = _calculate_boundary_distance(drawing_ctx)
        if calc:
            results.append(calc.model_dump())
            logger.debug(f"Boundary distance: {calc.result}m")

    if "height_check" in pending:
        calc = _calculate_height_check(drawing_ctx)
        if calc:
            results.append(calc.model_dump())
            logger.debug(f"Height: {calc.result}m (limit {calc.limit}m)")

    if "extension_depth" in pending:
        calc = _calculate_extension_depth(drawing_ctx, house_type)
        if calc:
            results.append(calc.model_dump())

    compliant_count = sum(1 for r in results if r.get("compliant", True))
    total_count = len(results)

    reasoning = f"Completed {total_count} calculations"
    if total_count > 0:
        reasoning += f": {compliant_count}/{total_count} compliant"

    return {
        "calculation_results": results,
        "pending_calculations": [],
        "reasoning_chain": add_reasoning_step(state, reasoning),
    }
