"""Calculator node for geometric calculations.

implementation integrating the geometry engine with the agent workflow.
Uses Shapely-based calculations via GeometryCalculator and SpatialInferenceEngine.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from app.agent.state import (
    AgentState,
    CalculationResult,
    add_reasoning_step,
)
from app.geometry.calculator import GeometryCalculator
from app.geometry.spatial_inference import DrawingParser, SpatialInferenceEngine
from app.geometry.types import SpatialAnalysisResult

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


class CalculatorNode:
    """LangGraph node that performs geometric calculations on drawing data.

    Integrates with:
    - GeometryCalculator: Core Shapely-based measurement functions
    - SpatialInferenceEngine: Semantic labeling (principal elevation, rear wall, etc.)
    - DrawingParser: Converts raw drawing objects to Shapely geometries
    """

    def __init__(self):
        self.calculator = GeometryCalculator()
        self.inference_engine = SpatialInferenceEngine()
        self.drawing_parser = DrawingParser()

    def __call__(self, state: AgentState) -> dict[str, Any]:
        """Process drawing context and perform calculations."""
        return self.calculate(state)

    def calculate(self, state: AgentState) -> dict[str, Any]:
        """Perform geometric calculations on drawing data.

        Args:
            state: Current agent state with drawing_context and raw_objects

        Returns:
            State updates with calculation_results and spatial_analysis
        """
        drawing_ctx = state.get("drawing_context") or {}
        raw_objects = state.get("raw_drawing_objects", [])
        pending = state.get("pending_calculations", [])
        query = state.get("user_query", "").lower()
        session_meta = self._extract_session_metadata(drawing_ctx)

        # Check for basic drawing context
        if not drawing_ctx.get("has_drawing") and not raw_objects:
            return {
                "calculation_results": [],
                "spatial_analysis": None,
                "pending_calculations": [],
                "reasoning_chain": add_reasoning_step(
                    state,
                    "No drawing context for calculations",
                ),
            }

        # Validate geometry from drawing context
        geometry_errors = _validate_geometry(drawing_ctx)
        if geometry_errors:
            logger.warning(f"Geometry validation errors: {geometry_errors}")
            return {
                "calculation_results": [],
                "spatial_analysis": None,
                "pending_calculations": [],
                "errors": state.get("errors", []) + geometry_errors,
                "should_escalate": True,
                "reasoning_chain": add_reasoning_step(
                    state,
                    f"Geometry validation failed: {len(geometry_errors)} issues",
                ),
            }

        # Parse raw drawing objects if available
        parsed = self._parse_objects(raw_objects) if raw_objects else None

        # Perform spatial analysis if we have parsed geometry
        spatial_analysis = None
        spatial_dict = None
        if parsed and parsed.get("walls"):
            spatial_analysis = self._perform_spatial_analysis(parsed, session_meta)
            spatial_dict = (
                spatial_analysis.to_dict() if spatial_analysis else None
            )

        # Perform calculations
        results = self._perform_calculations(
            drawing_ctx=drawing_ctx,
            parsed=parsed,
            spatial=spatial_analysis,
            pending=pending,
            query=query,
            session_meta=session_meta,
        )

        compliant_count = sum(1 for r in results if r.get("compliant", True))
        total_count = len(results)

        reasoning = f"Completed {total_count} calculations"
        if total_count > 0:
            reasoning += f": {compliant_count}/{total_count} compliant"
        if spatial_analysis:
            reasoning += f" | Spatial: {spatial_analysis.principal_direction or 'unknown'} facing"

        return {
            "calculation_results": results,
            "spatial_analysis": spatial_dict,
            "pending_calculations": [],
            "reasoning_chain": add_reasoning_step(state, reasoning),
        }

    def _extract_session_metadata(self, drawing_ctx: dict) -> dict:
        """Extract session metadata from drawing context."""
        return {
            "house_type": drawing_ctx.get("house_type"),
            "designated_land_type": drawing_ctx.get("designated_land_type"),
            "prior_extensions_sqm": drawing_ctx.get("prior_extensions_sqm"),
            "existing_eaves_height_m": drawing_ctx.get("eaves_height_m"),
            "existing_ridge_height_m": drawing_ctx.get("ridge_height_m"),
            "building_height_m": drawing_ctx.get("building_height_m"),
        }

    def _parse_objects(self, raw_objects: list[dict]) -> Optional[dict[str, Any]]:
        """Parse raw drawing objects into Shapely geometries."""
        if not raw_objects:
            return None

        try:
            return self.drawing_parser.parse(raw_objects)
        except Exception as e:
            logger.warning(f"Failed to parse drawing objects: {e}")
            return None

    def _perform_spatial_analysis(
        self,
        parsed: dict[str, Any],
        session_meta: dict,
    ) -> Optional[SpatialAnalysisResult]:
        """Perform spatial inference on parsed geometry."""
        try:
            return self.inference_engine.analyze(
                walls=parsed.get("walls", []),
                plot_boundary=parsed.get("plot_boundary"),
                highways=parsed.get("highways", []),
                doors=parsed.get("doors"),
                windows=parsed.get("windows"),
                session_metadata=session_meta,
            )
        except Exception as e:
            logger.warning(f"Spatial analysis failed: {e}")
            return None

    def _perform_calculations(
        self,
        drawing_ctx: dict,
        parsed: Optional[dict],
        spatial: Optional[SpatialAnalysisResult],
        pending: list[str],
        query: str,
        session_meta: dict,
    ) -> list[dict]:
        """Perform all requested calculations."""
        results: list[dict] = []

        # Determine what calculations to perform
        needs_area = "coverage_percentage" in pending or self._needs_area(query)
        needs_distance = "boundary_distance" in pending or self._needs_distance(query)
        needs_height = "height_check" in pending or self._needs_height(query)
        needs_extension = "extension_depth" in pending or self._needs_extension(query)
        needs_width = "width" in query.lower() or "side" in query.lower()

        # Use geometry engine if we have parsed geometry
        if parsed:
            if needs_area:
                results.extend(self._calculate_areas_from_geometry(parsed, spatial))
            if needs_distance:
                results.extend(self._calculate_distances_from_geometry(parsed))
            if needs_extension and spatial:
                results.extend(
                    self._calculate_extension_depth_from_geometry(parsed, spatial)
                )
            if needs_width and spatial:
                results.extend(self._calculate_widths_from_geometry(spatial))
        else:
            # Fallback to pre-calculated values from drawing context
            prior_extensions = drawing_ctx.get("prior_extensions_sqm", 0.0) or 0.0
            house_type = drawing_ctx.get("house_type")

            if needs_area:
                calc = self._calculate_coverage_from_context(
                    drawing_ctx, prior_extensions
                )
                if calc:
                    results.append(calc.model_dump())

            if needs_distance:
                calc = self._calculate_boundary_distance_from_context(drawing_ctx)
                if calc:
                    results.append(calc.model_dump())

            if needs_height:
                calc = self._calculate_height_from_context(drawing_ctx)
                if calc:
                    results.append(calc.model_dump())

        return results

    def _needs_area(self, query: str) -> bool:
        keywords = ["area", "size", "square", "coverage", "50%", "curtilage"]
        return any(kw in query for kw in keywords)

    def _needs_distance(self, query: str) -> bool:
        keywords = ["distance", "boundary", "metres from", "within", "how far", "2m"]
        return any(kw in query for kw in keywords)

    def _needs_height(self, query: str) -> bool:
        keywords = ["height", "tall", "eaves", "ridge", "metres high"]
        return any(kw in query for kw in keywords)

    def _needs_extension(self, query: str) -> bool:
        keywords = ["extension", "depth", "project", "extend", "rear", "beyond"]
        return any(kw in query for kw in keywords)

    def _calculate_areas_from_geometry(
        self,
        parsed: dict,
        spatial: Optional[SpatialAnalysisResult],
    ) -> list[dict]:
        """Calculate areas using Shapely geometry."""
        results = []
        from shapely.ops import unary_union

        plot_boundary = parsed.get("plot_boundary")
        walls = parsed.get("walls", [])

        if plot_boundary:
            area_result = self.calculator.calculate_polygon_area(
                list(plot_boundary.exterior.coords)
            )
            results.append(
                CalculationResult(
                    calculation_type="area",
                    input_values={"source": "plot_boundary"},
                    result=area_result["area"],
                    unit="m²",
                    notes="Plot boundary (curtilage) area from geometry",
                ).model_dump()
            )

        if walls:
            combined = unary_union(walls)
            building_area = combined.area * self.calculator.MM2_TO_M2
            results.append(
                CalculationResult(
                    calculation_type="area",
                    input_values={"source": "walls"},
                    result=round(building_area, 2),
                    unit="m²",
                    notes="Total building footprint from geometry",
                ).model_dump()
            )

        if plot_boundary and walls:
            original_footprint = (
                spatial.original_footprint if spatial else None
            )
            coverage = self.calculator.calculate_curtilage_coverage(
                plot_boundary=plot_boundary,
                buildings=walls,
                original_house=original_footprint,
            )

            compliant = coverage["compliant_50_percent"]
            margin = 50.0 - coverage["coverage_percent"]

            results.append(
                CalculationResult(
                    calculation_type="coverage_percentage",
                    input_values={
                        "building_area_m2": coverage["building_area_m2"],
                        "curtilage_area_m2": coverage["curtilage_area_m2"],
                    },
                    result=coverage["coverage_percent"],
                    unit="%",
                    limit=50.0,
                    limit_source="Class A.1(b) - 50% curtilage rule",
                    compliant=compliant,
                    margin=round(margin, 1),
                    notes=f"Remaining allowance: {coverage['remaining_allowance_m2']}m²",
                ).model_dump()
            )

        return results

    def _calculate_distances_from_geometry(self, parsed: dict) -> list[dict]:
        """Calculate distances using Shapely geometry."""
        results = []
        from shapely.ops import unary_union

        walls = parsed.get("walls", [])
        plot_boundary = parsed.get("plot_boundary")

        if walls and plot_boundary:
            combined = unary_union(walls)
            dist_result = self.calculator.calculate_min_distance_to_boundary(
                building=combined,
                boundary=plot_boundary,
            )

            distance_m = dist_result["min_distance_m"]
            compliant = distance_m >= 2.0
            margin = distance_m - 2.0

            notes = None
            if not compliant:
                notes = "Within 2m of boundary - eaves height limited to 3m"

            results.append(
                CalculationResult(
                    calculation_type="boundary_distance",
                    input_values={
                        "nearest_building_point": dist_result["nearest_building_point"],
                        "nearest_boundary_point": dist_result["nearest_boundary_point"],
                    },
                    result=distance_m,
                    unit="metres",
                    limit=2.0,
                    limit_source="Class A.1(i) - 2m boundary rule",
                    compliant=compliant,
                    margin=round(margin, 2),
                    notes=notes,
                ).model_dump()
            )

        return results

    def _calculate_extension_depth_from_geometry(
        self,
        parsed: dict,
        spatial: SpatialAnalysisResult,
    ) -> list[dict]:
        """Calculate extension depth using Shapely geometry."""
        results = []

        rear_wall = spatial.rear_wall
        extensions = parsed.get("extensions", [])

        # Try to get extensions from spatial analysis if not explicitly marked
        if not extensions and spatial.extensions:
            extensions = spatial.extensions

        if rear_wall and extensions:
            for i, ext in enumerate(extensions):
                depth_result = self.calculator.calculate_extension_depth(
                    extension=ext,
                    rear_wall=rear_wall,
                )

                results.append(
                    CalculationResult(
                        calculation_type="extension_depth",
                        input_values={"extension_index": i + 1},
                        result=depth_result["depth_m"],
                        unit="metres",
                        notes=f"Extension {i + 1} depth beyond rear wall",
                    ).model_dump()
                )

        return results

    def _calculate_widths_from_geometry(
        self,
        spatial: SpatialAnalysisResult,
    ) -> list[dict]:
        """Calculate building widths using Shapely geometry."""
        results = []

        original = spatial.original_footprint
        if original:
            width_result = self.calculator.calculate_building_width(original)

            results.append(
                CalculationResult(
                    calculation_type="width",
                    input_values={"source": "original_footprint"},
                    result=width_result["width_m"],
                    unit="metres",
                    notes="Original house width",
                ).model_dump()
            )

            half_width = round(width_result["width_m"] / 2, 2)
            results.append(
                CalculationResult(
                    calculation_type="max_side_extension_width",
                    input_values={"original_width_m": width_result["width_m"]},
                    result=half_width,
                    unit="metres",
                    limit=half_width,
                    limit_source="Class A.1(j)(iii) - half width rule",
                    notes="Maximum allowed side extension width (50% of original)",
                ).model_dump()
            )

        return results

    def _calculate_coverage_from_context(
        self,
        drawing_ctx: dict,
        prior_extensions_sqm: float = 0.0,
    ) -> Optional[CalculationResult]:
        """Fallback: Calculate coverage from pre-calculated context values."""
        plot_area = drawing_ctx.get("plot_area_sqm")
        building_footprint = drawing_ctx.get("building_footprint_sqm")

        if not plot_area or not building_footprint:
            return None

        percentage = (building_footprint / plot_area) * 100
        compliant = percentage <= 50.0
        margin = 50.0 - percentage

        notes = None
        if prior_extensions_sqm > 0:
            notes = f"Includes {prior_extensions_sqm}m² of prior extensions"

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

    def _calculate_boundary_distance_from_context(
        self,
        drawing_ctx: dict,
    ) -> Optional[CalculationResult]:
        """Fallback: Calculate boundary distance from pre-calculated context."""
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

    def _calculate_height_from_context(
        self,
        drawing_ctx: dict,
    ) -> Optional[CalculationResult]:
        """Fallback: Calculate height compliance from pre-calculated context."""
        building_height = drawing_ctx.get("building_height_m")
        eaves_height = drawing_ctx.get("eaves_height_m")
        distance_to_boundary = drawing_ctx.get("distance_to_boundary_m")

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
            notes=f"Checked {height_type} height",
        )


# Module-level instance for use as a node
_calculator = CalculatorNode()


async def calculator_node(state: AgentState) -> dict[str, Any]:
    """Async wrapper for CalculatorNode.

    This is the LangGraph node entry point that performs geometric calculations.

    Args:
        state: Current agent state with drawing_context and raw_drawing_objects

    Returns:
        State updates with calculation_results and spatial_analysis
    """
    return _calculator.calculate(state)
