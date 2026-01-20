"""Rule registry for UK Permitted Development compliance checking."""

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from app.geometry.types import (
    ComplianceCheckResult,
    HouseType,
    LandType,
)


@dataclass
class ComplianceRule:
    """A single compliance rule that can be evaluated."""

    rule_id: str
    class_reference: str
    pdf_page: int
    description: str
    applies_when: Callable[[dict], bool]
    check: Callable[[dict, "RuleRegistry"], ComplianceCheckResult]
    thresholds: dict[str, float] = field(default_factory=dict)


class RuleRegistry:
    """Central registry of all compliance rules from UK Permitted Development PDF."""

    def __init__(self):
        self.rules: dict[str, ComplianceRule] = {}
        self._register_all_rules()

    def _register_all_rules(self):
        """Register all Class A, B, C, D, E rules."""
        self._register_class_a_rules()
        self._register_class_b_rules()
        self._register_class_cde_rules()

    def _register_class_a_rules(self):
        """Register Class A extension rules."""

        self.rules["A.1(b)"] = ComplianceRule(
            rule_id="A.1(b)",
            class_reference="Class A, Section 1(b)",
            pdf_page=10,
            description="Total area of buildings must not exceed 50% of curtilage",
            applies_when=lambda ctx: True,
            check=self._check_coverage_rule,
            thresholds={"max_coverage": 0.5},
        )

        self.rules["A.1(f)"] = ComplianceRule(
            rule_id="A.1(f)",
            class_reference="Class A, Section 1(f)",
            pdf_page=17,
            description="Single-storey rear extension depth limit (4m detached, 3m other)",
            applies_when=lambda ctx: (
                ctx.get("extension_type") == "rear"
                and ctx.get("storeys", 1) == 1
                and ctx.get("land_type") != LandType.ARTICLE_2_3.value
            ),
            check=self._check_rear_extension_depth,
            thresholds={
                "detached": 4.0,
                "semi-detached": 3.0,
                "terraced": 3.0,
                "end-terrace": 3.0,
            },
        )

        self.rules["A.1(g)"] = ComplianceRule(
            rule_id="A.1(g)",
            class_reference="Class A, Section 1(g)",
            pdf_page=17,
            description="Larger rear extension with neighbour consultation (8m detached, 6m other)",
            applies_when=lambda ctx: (
                ctx.get("extension_type") == "rear"
                and ctx.get("storeys", 1) == 1
                and ctx.get("neighbour_consultation", False)
            ),
            check=self._check_larger_rear_extension,
            thresholds={
                "detached": 8.0,
                "semi-detached": 6.0,
                "terraced": 6.0,
                "end-terrace": 6.0,
            },
        )

        self.rules["A.1(h)"] = ComplianceRule(
            rule_id="A.1(h)",
            class_reference="Class A, Section 1(h)",
            pdf_page=20,
            description="Multi-storey rear extension: max 3m depth, 7m from rear boundary",
            applies_when=lambda ctx: (
                ctx.get("extension_type") == "rear" and ctx.get("storeys", 1) > 1
            ),
            check=self._check_multistorey_rear,
            thresholds={"max_depth": 3.0, "min_boundary_distance": 7.0},
        )

        self.rules["A.1(i)"] = ComplianceRule(
            rule_id="A.1(i)",
            class_reference="Class A, Section 1(i)",
            pdf_page=22,
            description="If within 2m of boundary, eaves max 3m",
            applies_when=lambda ctx: ctx.get("distance_to_boundary", float("inf")) < 2.0,
            check=self._check_boundary_eaves,
            thresholds={"boundary_distance": 2.0, "max_eaves": 3.0},
        )

        self.rules["A.1(j)"] = ComplianceRule(
            rule_id="A.1(j)",
            class_reference="Class A, Section 1(j)",
            pdf_page=22,
            description="Side extension: single storey, max 4m height, max half width",
            applies_when=lambda ctx: ctx.get("extension_type") == "side",
            check=self._check_side_extension,
            thresholds={"max_height": 4.0, "max_width_ratio": 0.5},
        )

        self.rules["A.1(e)"] = ComplianceRule(
            rule_id="A.1(e)",
            class_reference="Class A, Section 1(e)",
            pdf_page=14,
            description="Cannot extend beyond principal elevation fronting highway",
            applies_when=lambda ctx: True,
            check=self._check_principal_elevation,
            thresholds={},
        )

    def _register_class_b_rules(self):
        """Register Class B roof rules."""

        self.rules["B.1(d)"] = ComplianceRule(
            rule_id="B.1(d)",
            class_reference="Class B, Section 1(d)",
            pdf_page=34,
            description="Loft conversion volume: 40m3 terraced, 50m3 other",
            applies_when=lambda ctx: ctx.get("extension_type") == "loft",
            check=self._check_loft_volume,
            thresholds={"terraced": 40.0, "other": 50.0},
        )

        self.rules["B.2(b)"] = ComplianceRule(
            rule_id="B.2(b)",
            class_reference="Class B, Section 2(b)",
            pdf_page=35,
            description="Dormer must be set back 0.2m from eaves",
            applies_when=lambda ctx: ctx.get("has_dormer", False),
            check=self._check_dormer_setback,
            thresholds={"setback": 0.2},
        )

    def _register_class_cde_rules(self):
        """Register Class C, D, E rules."""

        self.rules["C.1(b)"] = ComplianceRule(
            rule_id="C.1(b)",
            class_reference="Class C, Section 1(b)",
            pdf_page=38,
            description="Rooflight must not protrude more than 0.15m",
            applies_when=lambda ctx: ctx.get("has_rooflight", False),
            check=self._check_rooflight_protrusion,
            thresholds={"max_protrusion": 0.15},
        )

        self.rules["D.1"] = ComplianceRule(
            rule_id="D.1",
            class_reference="Class D, Section 1",
            pdf_page=40,
            description="Porch: max 3m2 area, 3m height, 2m from highway",
            applies_when=lambda ctx: ctx.get("extension_type") == "porch",
            check=self._check_porch,
            thresholds={
                "max_area": 3.0,
                "max_height": 3.0,
                "min_highway_distance": 2.0,
            },
        )

        self.rules["E.1(e)"] = ComplianceRule(
            rule_id="E.1(e)",
            class_reference="Class E, Section 1(e)",
            pdf_page=43,
            description="Outbuilding height: 4m dual-pitch, 2.5m within 2m boundary, 3m other",
            applies_when=lambda ctx: ctx.get("extension_type") == "outbuilding",
            check=self._check_outbuilding_height,
            thresholds={
                "dual_pitched": 4.0,
                "within_2m_boundary": 2.5,
                "other": 3.0,
            },
        )

    def _check_coverage_rule(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        coverage = ctx.get("coverage_result", {})
        coverage_percent = coverage.get("coverage_percent", 0)
        compliant = coverage.get("compliant_50_percent", True)

        return ComplianceCheckResult(
            rule_id="A.1(b)",
            rule_description=self.rules["A.1(b)"].description,
            pdf_page=10,
            compliant=compliant,
            measured_value=coverage_percent,
            threshold=50.0,
            unit="%",
            message=f"Coverage is {coverage_percent}% of curtilage "
            f"({'compliant' if compliant else 'exceeds 50% limit'})",
        )

    def _check_rear_extension_depth(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        house_type = ctx.get("house_type", "semi-detached")
        threshold = self.rules["A.1(f)"].thresholds.get(house_type, 3.0)
        depth_m = ctx.get("extension_depth_m", 0)
        compliant = depth_m <= threshold

        return ComplianceCheckResult(
            rule_id="A.1(f)",
            rule_description=self.rules["A.1(f)"].description,
            pdf_page=17,
            compliant=compliant,
            measured_value=depth_m,
            threshold=threshold,
            unit="m",
            message=f"Rear extension depth is {depth_m}m "
            f"(limit for {house_type}: {threshold}m) "
            f"{'COMPLIANT' if compliant else 'EXCEEDS LIMIT'}",
        )

    def _check_larger_rear_extension(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        house_type = ctx.get("house_type", "semi-detached")
        threshold = self.rules["A.1(g)"].thresholds.get(house_type, 6.0)
        depth_m = ctx.get("extension_depth_m", 0)
        compliant = depth_m <= threshold

        return ComplianceCheckResult(
            rule_id="A.1(g)",
            rule_description=self.rules["A.1(g)"].description,
            pdf_page=17,
            compliant=compliant,
            measured_value=depth_m,
            threshold=threshold,
            unit="m",
            message=f"Under neighbour consultation: depth {depth_m}m "
            f"(limit: {threshold}m for {house_type}) "
            f"{'COMPLIANT' if compliant else 'EXCEEDS LIMIT'}",
        )

    def _check_multistorey_rear(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        depth_m = ctx.get("extension_depth_m", 0)
        boundary_dist_m = ctx.get("distance_to_boundary", 0)

        depth_compliant = depth_m <= 3.0
        boundary_compliant = boundary_dist_m >= 7.0

        checks = [
            {
                "check": "depth",
                "measured": depth_m,
                "threshold": 3.0,
                "unit": "m",
                "compliant": depth_compliant,
            },
            {
                "check": "boundary_distance",
                "measured": boundary_dist_m,
                "threshold": 7.0,
                "unit": "m",
                "compliant": boundary_compliant,
            },
        ]

        return ComplianceCheckResult(
            rule_id="A.1(h)",
            rule_description=self.rules["A.1(h)"].description,
            pdf_page=20,
            compliant=depth_compliant and boundary_compliant,
            measured_value=depth_m,
            threshold=3.0,
            unit="m",
            message=f"Multi-storey rear: depth {depth_m}m (max 3m), "
            f"boundary distance {boundary_dist_m}m (min 7m)",
            checks=checks,
        )

    def _check_boundary_eaves(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        eaves_height = ctx.get("eaves_height")
        distance_to_boundary = ctx.get("distance_to_boundary")

        if eaves_height is None:
            return ComplianceCheckResult(
                rule_id="A.1(i)",
                rule_description=self.rules["A.1(i)"].description,
                pdf_page=22,
                compliant=None,
                error="Eaves height not provided",
                message="Cannot check boundary eaves rule: eaves height not specified",
            )

        compliant = eaves_height <= 3.0

        return ComplianceCheckResult(
            rule_id="A.1(i)",
            rule_description=self.rules["A.1(i)"].description,
            pdf_page=22,
            compliant=compliant,
            measured_value=eaves_height,
            threshold=3.0,
            unit="m",
            message=f"Eaves height is {eaves_height}m at {distance_to_boundary}m from boundary "
            f"(max 3m when within 2m) {'COMPLIANT' if compliant else 'EXCEEDS LIMIT'}",
        )

    def _check_side_extension(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        width_result = ctx.get("width_result", {})
        width_compliant = width_result.get("compliant", True)
        extension_width = width_result.get("extension_width_m", 0)
        half_original = width_result.get("half_original_width_m", 0)

        height = ctx.get("extension_height")
        height_compliant = height <= 4.0 if height else None

        overall = width_compliant and (height_compliant is None or height_compliant)

        checks = [
            {
                "check": "width_ratio",
                "extension_width_m": extension_width,
                "threshold_m": half_original,
                "compliant": width_compliant,
            },
            {
                "check": "height",
                "measured": height,
                "threshold": 4.0,
                "unit": "m",
                "compliant": height_compliant,
            },
        ]

        return ComplianceCheckResult(
            rule_id="A.1(j)",
            rule_description=self.rules["A.1(j)"].description,
            pdf_page=22,
            compliant=overall,
            measured_value=extension_width,
            threshold=half_original,
            unit="m",
            message=f"Side extension: width {extension_width}m "
            f"(max {half_original}m = half of original)",
            checks=checks,
        )

    def _check_principal_elevation(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        extends_beyond = ctx.get("extends_beyond_principal", False)

        return ComplianceCheckResult(
            rule_id="A.1(e)",
            rule_description=self.rules["A.1(e)"].description,
            pdf_page=14,
            compliant=not extends_beyond,
            message=f"Extension {'does NOT' if not extends_beyond else 'DOES'} "
            f"extend beyond the principal elevation",
        )

    def _check_loft_volume(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        house_type = ctx.get("house_type", "semi-detached")
        volume = ctx.get("loft_volume")

        threshold = 40.0 if house_type == "terraced" else 50.0

        if volume is None:
            return ComplianceCheckResult(
                rule_id="B.1(d)",
                rule_description=self.rules["B.1(d)"].description,
                pdf_page=34,
                compliant=None,
                error="Loft volume not provided",
                message="Cannot check volume rule: volume not specified",
            )

        compliant = volume <= threshold

        return ComplianceCheckResult(
            rule_id="B.1(d)",
            rule_description=self.rules["B.1(d)"].description,
            pdf_page=34,
            compliant=compliant,
            measured_value=volume,
            threshold=threshold,
            unit="m3",
            message=f"Loft volume is {volume}m3 (max {threshold}m3 for {house_type})",
        )

    def _check_dormer_setback(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        setback = ctx.get("dormer_setback")

        if setback is None:
            return ComplianceCheckResult(
                rule_id="B.2(b)",
                rule_description=self.rules["B.2(b)"].description,
                pdf_page=35,
                compliant=None,
                error="Dormer setback not provided",
            )

        compliant = setback >= 0.2

        return ComplianceCheckResult(
            rule_id="B.2(b)",
            rule_description=self.rules["B.2(b)"].description,
            pdf_page=35,
            compliant=compliant,
            measured_value=setback,
            threshold=0.2,
            unit="m",
            message=f"Dormer setback is {setback}m (min 0.2m required)",
        )

    def _check_rooflight_protrusion(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        protrusion = ctx.get("rooflight_protrusion")

        if protrusion is None:
            return ComplianceCheckResult(
                rule_id="C.1(b)",
                rule_description=self.rules["C.1(b)"].description,
                pdf_page=38,
                compliant=None,
                error="Rooflight protrusion not provided",
            )

        compliant = protrusion <= 0.15

        return ComplianceCheckResult(
            rule_id="C.1(b)",
            rule_description=self.rules["C.1(b)"].description,
            pdf_page=38,
            compliant=compliant,
            measured_value=protrusion,
            threshold=0.15,
            unit="m",
            message=f"Rooflight protrusion is {protrusion}m (max 0.15m allowed)",
        )

    def _check_porch(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        area = ctx.get("porch_area", 0)
        height = ctx.get("porch_height")
        highway_dist = ctx.get("highway_distance")

        area_compliant = area <= 3.0
        height_compliant = height <= 3.0 if height else None
        highway_compliant = highway_dist >= 2.0 if highway_dist else None

        checks = [
            {
                "check": "area",
                "measured": area,
                "threshold": 3.0,
                "unit": "m2",
                "compliant": area_compliant,
            },
            {
                "check": "height",
                "measured": height,
                "threshold": 3.0,
                "unit": "m",
                "compliant": height_compliant,
            },
            {
                "check": "highway_distance",
                "measured": highway_dist,
                "threshold": 2.0,
                "unit": "m",
                "compliant": highway_compliant,
            },
        ]

        all_checks = [c["compliant"] for c in checks if c["compliant"] is not None]
        overall = all(all_checks) if all_checks else None

        return ComplianceCheckResult(
            rule_id="D.1",
            rule_description=self.rules["D.1"].description,
            pdf_page=40,
            compliant=overall,
            measured_value=area,
            threshold=3.0,
            unit="m2",
            message=f"Porch area {area}m2, height {height}m, highway distance {highway_dist}m",
            checks=checks,
        )

    def _check_outbuilding_height(
        self, ctx: dict, registry: "RuleRegistry"
    ) -> ComplianceCheckResult:
        height = ctx.get("outbuilding_height")
        roof_type = ctx.get("roof_type", "other")
        distance_to_boundary = ctx.get("distance_to_boundary")

        if distance_to_boundary and distance_to_boundary < 2:
            threshold = 2.5
            rule_detail = "within 2m of boundary"
        elif roof_type == "dual_pitched":
            threshold = 4.0
            rule_detail = "dual-pitched roof"
        else:
            threshold = 3.0
            rule_detail = "other roof type"

        if height is None:
            return ComplianceCheckResult(
                rule_id="E.1(e)",
                rule_description=self.rules["E.1(e)"].description,
                pdf_page=43,
                compliant=None,
                error="Outbuilding height not provided",
            )

        compliant = height <= threshold

        return ComplianceCheckResult(
            rule_id="E.1(e)",
            rule_description=self.rules["E.1(e)"].description,
            pdf_page=43,
            compliant=compliant,
            measured_value=height,
            threshold=threshold,
            unit="m",
            message=f"Outbuilding height {height}m (max {threshold}m for {rule_detail})",
        )

    def get_applicable_rules(self, context: dict) -> list[ComplianceRule]:
        """Get all rules that apply to the given context."""
        return [rule for rule in self.rules.values() if rule.applies_when(context)]

    def evaluate_all(self, context: dict) -> dict[str, Any]:
        """Evaluate all applicable rules for the given context."""
        applicable = self.get_applicable_rules(context)
        results = []

        for rule in applicable:
            try:
                result = rule.check(context, self)
                results.append(result.to_dict())
            except Exception as e:
                results.append(
                    {
                        "rule_id": rule.rule_id,
                        "error": str(e),
                        "compliant": None,
                    }
                )

        compliant_results = [r for r in results if r.get("compliant") is not None]

        return {
            "overall_compliant": (
                all(r["compliant"] for r in compliant_results)
                if compliant_results
                else None
            ),
            "rules_checked": len(results),
            "rules_passed": sum(1 for r in results if r.get("compliant") is True),
            "rules_failed": sum(1 for r in results if r.get("compliant") is False),
            "rules_inconclusive": sum(
                1 for r in results if r.get("compliant") is None
            ),
            "results": results,
            "verdict": self._generate_verdict(results),
        }

    def _generate_verdict(self, results: list[dict]) -> str:
        """Generate a human-readable verdict."""
        failed = [r for r in results if r.get("compliant") is False]

        if not failed:
            return "COMPLIANT: All checked rules pass"

        verdict_parts = ["NON_COMPLIANT: The following rules are violated:"]
        for f in failed:
            verdict_parts.append(f"  {f['rule_id']}: {f.get('message', 'Check failed')}")

        return "\n".join(verdict_parts)
