"""Unit tests for GeometryCalculator."""

import pytest
from shapely.geometry import LineString, Polygon

from app.geometry.calculator import GeometryCalculator


@pytest.fixture
def calculator():
    return GeometryCalculator()


@pytest.fixture
def simple_square():
    """10m x 10m square (10000mm x 10000mm)."""
    return Polygon([
        (0, 0), (10000, 0), (10000, 10000), (0, 10000), (0, 0)
    ])


@pytest.fixture
def plot_boundary():
    """20m x 20m plot."""
    return Polygon([
        (0, 0), (20000, 0), (20000, 20000), (0, 20000), (0, 0)
    ])


class TestPolygonArea:
    def test_simple_square(self, calculator):
        points = [(0, 0), (10000, 0), (10000, 10000), (0, 10000)]
        result = calculator.calculate_polygon_area(points)
        assert result["area"] == 100.0
        assert result["unit"] == "m2"

    def test_rectangle(self, calculator):
        points = [(0, 0), (5000, 0), (5000, 10000), (0, 10000)]
        result = calculator.calculate_polygon_area(points)
        assert result["area"] == 50.0

    def test_insufficient_points(self, calculator):
        result = calculator.calculate_polygon_area([(0, 0), (1, 1)])
        assert result.get("error") is not None


class TestCurtilageCoverage:
    def test_25_percent_coverage(self, calculator, simple_square, plot_boundary):
        result = calculator.calculate_curtilage_coverage(
            plot_boundary=plot_boundary,
            buildings=[simple_square],
        )
        assert result["coverage_percent"] == 25.0
        assert result["compliant_50_percent"] is True

    def test_exceeds_50_percent(self, calculator, plot_boundary):
        large_building = Polygon([
            (0, 0), (15000, 0), (15000, 15000), (0, 15000)
        ])
        result = calculator.calculate_curtilage_coverage(
            plot_boundary=plot_boundary,
            buildings=[large_building],
        )
        assert result["coverage_percent"] > 50.0
        assert result["compliant_50_percent"] is False


class TestDistanceCalculations:
    def test_distance_to_boundary(self, calculator, plot_boundary):
        building = Polygon([
            (5000, 5000), (15000, 5000), (15000, 15000), (5000, 15000)
        ])
        result = calculator.calculate_min_distance_to_boundary(
            building=building,
            boundary=plot_boundary,
        )
        assert result["min_distance_m"] == 5.0
        assert result["within_2m"] is False

    def test_within_2m_of_boundary(self, calculator, plot_boundary):
        building = Polygon([
            (500, 500), (10000, 500), (10000, 10000), (500, 10000)
        ])
        result = calculator.calculate_min_distance_to_boundary(
            building=building,
            boundary=plot_boundary,
        )
        assert result["min_distance_m"] == 0.5
        assert result["within_2m"] is True


class TestExtensionDepth:
    def test_extension_depth(self, calculator):
        rear_wall = LineString([(0, 10000), (10000, 10000)])
        extension = Polygon([
            (2000, 10000), (8000, 10000), (8000, 14000), (2000, 14000)
        ])
        result = calculator.calculate_extension_depth(
            extension=extension,
            rear_wall=rear_wall,
        )
        assert result["depth_m"] == 4.0


class TestBuildingWidth:
    def test_square_building_width(self, calculator, simple_square):
        result = calculator.calculate_building_width(simple_square)
        assert result["width_m"] == 10.0
        assert result["length_m"] == 10.0

    def test_rectangular_building(self, calculator):
        rectangle = Polygon([
            (0, 0), (5000, 0), (5000, 10000), (0, 10000)
        ])
        result = calculator.calculate_building_width(rectangle)
        assert result["width_m"] == 5.0
        assert result["length_m"] == 10.0


class TestHalfWidthRule:
    def test_compliant_side_extension(self, calculator, simple_square):
        extension = Polygon([
            (10000, 0), (14000, 0), (14000, 10000), (10000, 10000)
        ])
        result = calculator.check_half_width_rule(
            original_house=simple_square,
            extension=extension,
        )
        assert result["compliant"] is True
        assert result["extension_width_m"] == 4.0
        assert result["half_original_width_m"] == 5.0

    def test_non_compliant_side_extension(self, calculator, simple_square):
        extension = Polygon([
            (10000, 0), (17000, 0), (17000, 10000), (10000, 10000)
        ])
        result = calculator.check_half_width_rule(
            original_house=simple_square,
            extension=extension,
        )
        assert result["compliant"] is False
        assert result["extension_width_m"] == 7.0
