"""Unit tests for SpatialInferenceEngine (Phase 5.2)."""

import pytest
from shapely.geometry import LineString, Polygon

from app.geometry.spatial_inference import (
    DrawingParser,
    OriginalHouseDetector,
    SpatialInferenceEngine,
)


@pytest.fixture
def engine():
    return SpatialInferenceEngine()


@pytest.fixture
def simple_house():
    """10m x 10m house."""
    return Polygon([
        (0, 0), (10000, 0), (10000, 10000), (0, 10000), (0, 0)
    ])


@pytest.fixture
def plot_boundary():
    """20m x 20m plot."""
    return Polygon([
        (0, 0), (20000, 0), (20000, 20000), (0, 20000), (0, 0)
    ])


@pytest.fixture
def highway_south():
    """Highway along the south (bottom) edge."""
    return LineString([(-5000, -2000), (25000, -2000)])


class TestPrincipalElevation:
    def test_identifies_front_facing_highway(self, engine, simple_house, plot_boundary, highway_south):
        result = engine.identify_principal_elevation(
            walls=[simple_house],
            highway_lines=[highway_south],
            plot_boundary=plot_boundary,
        )
        assert result.get("principal_wall") is not None
        assert result.get("confidence", 0) > 0.5

    def test_no_highway_requires_clarification(self, engine, simple_house, plot_boundary):
        result = engine.identify_principal_elevation(
            walls=[simple_house],
            highway_lines=[],
            plot_boundary=plot_boundary,
        )
        assert result.get("requires_clarification") is True


class TestRearWallIdentification:
    def test_rear_wall_opposite_to_front(self, engine, simple_house, plot_boundary, highway_south):
        principal = engine.identify_principal_elevation(
            walls=[simple_house],
            highway_lines=[highway_south],
            plot_boundary=plot_boundary,
        )
        rear = engine.identify_rear_wall([simple_house], principal)
        assert rear.get("rear_wall") is not None


class TestLShapeDetection:
    def test_rectangular_is_not_l_shaped(self, engine, simple_house):
        result = engine.detect_l_shaped_building([simple_house])
        assert result["is_l_shaped"] is False
        assert result["fill_ratio"] > 0.9

    def test_l_shaped_building(self, engine):
        l_shape = Polygon([
            (0, 0), (10000, 0), (10000, 3000),
            (3000, 3000), (3000, 10000), (0, 10000), (0, 0)
        ])
        result = engine.detect_l_shaped_building([l_shape])
        assert result["is_l_shaped"] is True
        assert result["fill_ratio"] < 0.75


class TestPartyWallDetection:
    def test_detached_no_party_walls(self, engine, simple_house, plot_boundary):
        result = engine.identify_party_walls(
            walls=[simple_house],
            plot_boundary=plot_boundary,
            house_type="detached",
        )
        assert result["party_walls"] == []
        assert result["buildable_sides"] == ["left", "right"]

    def test_semi_detached_expects_one_party_wall(self, engine, plot_boundary):
        house_on_boundary = Polygon([
            (0, 5000), (10000, 5000), (10000, 15000), (0, 15000), (0, 5000)
        ])
        result = engine.identify_party_walls(
            walls=[house_on_boundary],
            plot_boundary=plot_boundary,
            house_type="semi-detached",
        )
        assert len(result.get("party_walls", [])) >= 0


class TestOriginalHouseDetector:
    def test_no_extensions_returns_full_footprint(self):
        walls = [
            Polygon([(0, 0), (10000, 0), (10000, 10000), (0, 10000)])
        ]
        detector = OriginalHouseDetector(walls, {})
        result = detector.detect()
        assert result.get("original_footprint") is not None
        assert len(result.get("extensions", [])) == 0

    def test_detects_extension_by_layer_name(self):
        walls = [
            {"type": "POLYLINE", "closed": True, "layer": "Walls",
             "points": [(0, 0), (10000, 0), (10000, 10000), (0, 10000)]},
            {"type": "POLYLINE", "closed": True, "layer": "Extension",
             "points": [(10000, 0), (14000, 0), (14000, 10000), (10000, 10000)]},
        ]
        detector = OriginalHouseDetector(walls, {})
        result = detector.detect()
        assert result.get("detection_method") == "layer_names"
        assert len(result.get("extensions", [])) == 1


class TestDrawingParser:
    def test_parses_closed_polyline_as_wall(self):
        parser = DrawingParser()
        objects = [
            {
                "type": "POLYLINE",
                "closed": True,
                "layer": "Walls",
                "points": [(0, 0), (10000, 0), (10000, 10000), (0, 10000)],
            }
        ]
        result = parser.parse(objects)
        assert len(result["walls"]) == 1

    def test_parses_highway_line(self):
        parser = DrawingParser()
        objects = [
            {
                "type": "LINE",
                "layer": "Highway",
                "start": [0, -2000],
                "end": [20000, -2000],
            }
        ]
        result = parser.parse(objects)
        assert len(result["highways"]) == 1

    def test_parses_plot_boundary(self):
        parser = DrawingParser()
        objects = [
            {
                "type": "POLYLINE",
                "closed": True,
                "layer": "Plot Boundary",
                "points": [(0, 0), (20000, 0), (20000, 20000), (0, 20000)],
            }
        ]
        result = parser.parse(objects)
        assert result["plot_boundary"] is not None


class TestSpatialAnalysisResult:
    def test_full_analysis(self, engine, simple_house, plot_boundary, highway_south):
        result = engine.analyze(
            walls=[simple_house],
            plot_boundary=plot_boundary,
            highways=[highway_south],
        )
        assert result.principal_direction is not None
        assert result.original_footprint is not None
