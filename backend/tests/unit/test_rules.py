"""Unit tests for RuleRegistry (Phase 5.3)."""

import pytest

from app.geometry.rules import RuleRegistry
from app.geometry.types import HouseType, LandType


@pytest.fixture
def registry():
    return RuleRegistry()


class TestRuleRegistration:
    def test_all_class_a_rules_registered(self, registry):
        class_a_rules = ["A.1(b)", "A.1(e)", "A.1(f)", "A.1(g)", "A.1(h)", "A.1(i)", "A.1(j)"]
        for rule_id in class_a_rules:
            assert rule_id in registry.rules

    def test_all_class_b_rules_registered(self, registry):
        class_b_rules = ["B.1(d)", "B.2(b)"]
        for rule_id in class_b_rules:
            assert rule_id in registry.rules

    def test_all_class_cde_rules_registered(self, registry):
        other_rules = ["C.1(b)", "D.1", "E.1(e)"]
        for rule_id in other_rules:
            assert rule_id in registry.rules


class TestCoverageRule:
    def test_compliant_coverage(self, registry):
        ctx = {
            "coverage_result": {
                "coverage_percent": 35.0,
                "compliant_50_percent": True,
            }
        }
        result = registry.rules["A.1(b)"].check(ctx, registry)
        assert result.compliant is True
        assert result.measured_value == 35.0

    def test_non_compliant_coverage(self, registry):
        ctx = {
            "coverage_result": {
                "coverage_percent": 55.0,
                "compliant_50_percent": False,
            }
        }
        result = registry.rules["A.1(b)"].check(ctx, registry)
        assert result.compliant is False


class TestRearExtensionDepth:
    def test_detached_4m_limit(self, registry):
        ctx = {
            "extension_type": "rear",
            "storeys": 1,
            "house_type": "detached",
            "extension_depth_m": 3.5,
        }
        result = registry.rules["A.1(f)"].check(ctx, registry)
        assert result.compliant is True
        assert result.threshold == 4.0

    def test_semi_detached_3m_limit(self, registry):
        ctx = {
            "extension_type": "rear",
            "storeys": 1,
            "house_type": "semi-detached",
            "extension_depth_m": 3.5,
        }
        result = registry.rules["A.1(f)"].check(ctx, registry)
        assert result.compliant is False
        assert result.threshold == 3.0


class TestBoundaryEavesRule:
    def test_within_2m_compliant(self, registry):
        ctx = {
            "distance_to_boundary": 1.5,
            "eaves_height": 2.8,
        }
        result = registry.rules["A.1(i)"].check(ctx, registry)
        assert result.compliant is True

    def test_within_2m_non_compliant(self, registry):
        ctx = {
            "distance_to_boundary": 1.5,
            "eaves_height": 3.5,
        }
        result = registry.rules["A.1(i)"].check(ctx, registry)
        assert result.compliant is False


class TestSideExtensionRule:
    def test_compliant_side_extension(self, registry):
        ctx = {
            "extension_type": "side",
            "width_result": {
                "compliant": True,
                "extension_width_m": 4.0,
                "half_original_width_m": 5.0,
            },
            "extension_height": 3.5,
        }
        result = registry.rules["A.1(j)"].check(ctx, registry)
        assert result.compliant is True

    def test_non_compliant_width(self, registry):
        ctx = {
            "extension_type": "side",
            "width_result": {
                "compliant": False,
                "extension_width_m": 6.0,
                "half_original_width_m": 5.0,
            },
        }
        result = registry.rules["A.1(j)"].check(ctx, registry)
        assert result.compliant is False


class TestLoftVolumeRule:
    def test_terraced_40m3_limit(self, registry):
        ctx = {
            "extension_type": "loft",
            "house_type": "terraced",
            "loft_volume": 35,
        }
        result = registry.rules["B.1(d)"].check(ctx, registry)
        assert result.compliant is True
        assert result.threshold == 40.0

    def test_detached_50m3_limit(self, registry):
        ctx = {
            "extension_type": "loft",
            "house_type": "detached",
            "loft_volume": 45,
        }
        result = registry.rules["B.1(d)"].check(ctx, registry)
        assert result.compliant is True
        assert result.threshold == 50.0


class TestOutbuildingHeight:
    def test_within_2m_boundary_limit(self, registry):
        ctx = {
            "extension_type": "outbuilding",
            "distance_to_boundary": 1.5,
            "outbuilding_height": 2.3,
        }
        result = registry.rules["E.1(e)"].check(ctx, registry)
        assert result.compliant is True
        assert result.threshold == 2.5

    def test_dual_pitched_4m_limit(self, registry):
        ctx = {
            "extension_type": "outbuilding",
            "distance_to_boundary": 5.0,
            "roof_type": "dual_pitched",
            "outbuilding_height": 3.8,
        }
        result = registry.rules["E.1(e)"].check(ctx, registry)
        assert result.compliant is True
        assert result.threshold == 4.0


class TestPorchRule:
    def test_compliant_porch(self, registry):
        ctx = {
            "extension_type": "porch",
            "porch_area": 2.5,
            "porch_height": 2.8,
            "highway_distance": 3.0,
        }
        result = registry.rules["D.1"].check(ctx, registry)
        assert result.compliant is True


class TestRuleApplicability:
    def test_coverage_always_applies(self, registry):
        applicable = registry.get_applicable_rules({})
        rule_ids = [r.rule_id for r in applicable]
        assert "A.1(b)" in rule_ids

    def test_rear_extension_applies_when_type_matches(self, registry):
        ctx = {"extension_type": "rear", "storeys": 1}
        applicable = registry.get_applicable_rules(ctx)
        rule_ids = [r.rule_id for r in applicable]
        assert "A.1(f)" in rule_ids

    def test_side_extension_applies_when_type_matches(self, registry):
        ctx = {"extension_type": "side"}
        applicable = registry.get_applicable_rules(ctx)
        rule_ids = [r.rule_id for r in applicable]
        assert "A.1(j)" in rule_ids


class TestEvaluateAll:
    def test_evaluate_returns_verdict(self, registry):
        ctx = {
            "coverage_result": {
                "coverage_percent": 35.0,
                "compliant_50_percent": True,
            }
        }
        result = registry.evaluate_all(ctx)
        assert "verdict" in result
        assert "overall_compliant" in result
        assert result["rules_checked"] >= 1

    def test_non_compliant_verdict(self, registry):
        ctx = {
            "coverage_result": {
                "coverage_percent": 60.0,
                "compliant_50_percent": False,
            }
        }
        result = registry.evaluate_all(ctx)
        assert result["overall_compliant"] is False
        assert "NON_COMPLIANT" in result["verdict"]
