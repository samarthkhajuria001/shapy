"""Core geometry calculation engine using Shapely.

Provides precise geometric calculations for UK Permitted Development compliance.
All internal measurements are in millimeters, converted to meters for output.
"""

import math
from typing import Any, Optional

from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import nearest_points, unary_union

from app.geometry.types import CalculationOutput


class GeometryCalculator:
    """Core calculation engine using Shapely for geometric operations."""

    MM_TO_M = 1 / 1000
    MM2_TO_M2 = 1 / 1_000_000
    MM3_TO_M3 = 1 / 1_000_000_000

    def calculate_polygon_area(
        self,
        points: list[tuple[float, float]],
        unit: str = "m2",
    ) -> dict[str, Any]:
        """Calculate area of a polygon using Shapely.

        Args:
            points: List of (x, y) coordinates in mm
            unit: Output unit, either "mm2" or "m2"

        Returns:
            Dictionary with area, unit, and polygon object
        """
        if len(points) < 3:
            return {"error": "Need at least 3 points", "area": 0, "polygon": None}

        if points[0] != points[-1]:
            points = points + [points[0]]

        polygon = Polygon(points)

        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        area_mm2 = polygon.area

        if unit == "m2":
            return {
                "area": round(area_mm2 * self.MM2_TO_M2, 2),
                "unit": "m2",
                "polygon": polygon,
            }
        return {"area": area_mm2, "unit": "mm2", "polygon": polygon}

    def calculate_curtilage_coverage(
        self,
        plot_boundary: Polygon,
        buildings: list[Polygon],
        original_house: Optional[Polygon] = None,
    ) -> dict[str, Any]:
        """Calculate building coverage ratio per Class A.1(b).

        The 50% rule: Total area of buildings (excluding original house)
        must not exceed 50% of curtilage (excluding original house area).

        Args:
            plot_boundary: The curtilage/plot polygon
            buildings: All building footprints
            original_house: The original dwelling footprint (to exclude)

        Returns:
            Dictionary with coverage calculations and compliance status
        """
        curtilage_area = plot_boundary.area

        all_buildings = unary_union(buildings)
        total_building_area = all_buildings.area

        if original_house and original_house.area > 0:
            available_curtilage = curtilage_area - original_house.area
            added_building_area = total_building_area - original_house.area
        else:
            available_curtilage = curtilage_area
            added_building_area = total_building_area

        if available_curtilage <= 0:
            coverage_ratio = 1.0
        else:
            coverage_ratio = added_building_area / available_curtilage

        remaining = max(0, (0.5 * available_curtilage - added_building_area))

        return {
            "curtilage_area_m2": round(curtilage_area * self.MM2_TO_M2, 2),
            "available_curtilage_m2": round(available_curtilage * self.MM2_TO_M2, 2),
            "building_area_m2": round(added_building_area * self.MM2_TO_M2, 2),
            "coverage_ratio": round(coverage_ratio, 4),
            "coverage_percent": round(coverage_ratio * 100, 1),
            "compliant_50_percent": coverage_ratio <= 0.5,
            "remaining_allowance_m2": round(remaining * self.MM2_TO_M2, 2),
        }

    def calculate_extension_depth(
        self,
        extension: Polygon,
        rear_wall: LineString,
    ) -> dict[str, Any]:
        """Calculate how far an extension projects beyond a rear wall.

        Measurement is from the base of the rear wall to the outer edge
        of the extension wall, perpendicular to the rear wall.

        Args:
            extension: The extension polygon
            rear_wall: The rear wall line segment

        Returns:
            Dictionary with depth measurements
        """
        extension_coords = list(extension.exterior.coords)
        max_distance = 0

        for point in extension_coords:
            pt = Point(point)
            distance = rear_wall.distance(pt)

            if self._is_behind_line(pt, rear_wall):
                max_distance = max(max_distance, distance)

        return {
            "depth_mm": round(max_distance, 0),
            "depth_m": round(max_distance * self.MM_TO_M, 2),
        }

    def calculate_min_distance_to_boundary(
        self,
        building: Polygon,
        boundary: Polygon,
    ) -> dict[str, Any]:
        """Calculate minimum distance from building to plot boundary.

        Used for the 2-metre boundary rule (Class A.1(i)).

        Args:
            building: Building footprint polygon
            boundary: Plot boundary polygon

        Returns:
            Dictionary with distance and compliance info
        """
        boundary_ring = boundary.exterior
        building_ring = building.exterior

        p1, p2 = nearest_points(building_ring, boundary_ring)
        min_distance = p1.distance(p2)

        return {
            "min_distance_mm": round(min_distance, 0),
            "min_distance_m": round(min_distance * self.MM_TO_M, 2),
            "nearest_building_point": (p1.x, p1.y),
            "nearest_boundary_point": (p2.x, p2.y),
            "within_2m": min_distance < 2000,
        }

    def calculate_distance_to_highway(
        self,
        building: Polygon,
        highways: list[LineString],
    ) -> dict[str, Any]:
        """Calculate distance from building to nearest highway.

        Args:
            building: Building footprint polygon
            highways: List of highway line segments

        Returns:
            Dictionary with distance to nearest highway
        """
        if not highways:
            return {"error": "No highways provided", "distance_m": None}

        min_distance = float("inf")
        nearest_highway = None

        building_ring = building.exterior

        for highway in highways:
            distance = building_ring.distance(highway)
            if distance < min_distance:
                min_distance = distance
                nearest_highway = highway

        return {
            "min_distance_mm": round(min_distance, 0),
            "min_distance_m": round(min_distance * self.MM_TO_M, 2),
            "nearest_highway": nearest_highway,
        }

    def calculate_building_width(
        self,
        building: Polygon,
        direction: str = "auto",
    ) -> dict[str, Any]:
        """Calculate the width of a building footprint.

        Width is measured perpendicular to the principal elevation.
        For the side extension rule (Class A.1(j)(iii)).

        Args:
            building: Building footprint polygon
            direction: "auto" to detect, or "x"/"y" for specific axis

        Returns:
            Dictionary with width and length measurements
        """
        if direction == "auto":
            mbr = building.minimum_rotated_rectangle
            mbr_coords = list(mbr.exterior.coords)

            edge1 = LineString([mbr_coords[0], mbr_coords[1]]).length
            edge2 = LineString([mbr_coords[1], mbr_coords[2]]).length

            width = min(edge1, edge2)
            length = max(edge1, edge2)
        else:
            minx, miny, maxx, maxy = building.bounds
            if direction == "x":
                width = maxx - minx
                length = maxy - miny
            else:
                width = maxy - miny
                length = maxx - minx

        return {
            "width_mm": round(width, 0),
            "width_m": round(width * self.MM_TO_M, 2),
            "length_mm": round(length, 0),
            "length_m": round(length * self.MM_TO_M, 2),
        }

    def check_half_width_rule(
        self,
        original_house: Polygon,
        extension: Polygon,
    ) -> dict[str, Any]:
        """Check if side extension exceeds half the width of original house.

        Per Class A.1(j)(iii): Side extension must not have a width greater
        than half the width of the original dwellinghouse.

        Args:
            original_house: Original house footprint
            extension: Extension footprint

        Returns:
            Dictionary with width comparison and compliance status
        """
        original_dims = self.calculate_building_width(original_house)
        extension_dims = self.calculate_building_width(extension)

        original_width = original_dims["width_m"]
        extension_width = extension_dims["width_m"]

        half_original = original_width / 2
        compliant = extension_width <= half_original

        return {
            "original_width_m": original_width,
            "extension_width_m": extension_width,
            "half_original_width_m": round(half_original, 2),
            "compliant": compliant,
            "excess_m": round(max(0, extension_width - half_original), 2),
        }

    def check_extends_beyond_wall(
        self,
        extension: Polygon,
        reference_wall: LineString,
        boundary: Polygon,
    ) -> dict[str, Any]:
        """Check if extension extends beyond a wall line to the boundary.

        Per PDF Page 14: 'extend beyond a wall' comprises not only the area
        immediately in front of the wall, but also an area in front of a line
        drawn from the end of the wall to the boundary of the property.

        Args:
            extension: Extension polygon
            reference_wall: Principal or side wall to check against
            boundary: Plot boundary polygon

        Returns:
            Dictionary with extension status
        """
        extended_line = self._extend_line_to_boundary(reference_wall, boundary)
        extension_intersects = extended_line.intersects(extension)

        if extension_intersects:
            return {
                "extends_beyond": True,
                "reference_line": extended_line,
            }

        return {
            "extends_beyond": False,
            "reference_line": extended_line,
        }

    def _is_behind_line(self, point: Point, line: LineString) -> bool:
        """Check if a point is on the rear side of a line using cross product."""
        line_coords = list(line.coords)
        if len(line_coords) < 2:
            return False

        x1, y1 = line_coords[0]
        x2, y2 = line_coords[1]
        px, py = point.x, point.y

        cross = (x2 - x1) * (py - y1) - (y2 - y1) * (px - x1)
        return cross > 0

    def _extend_line_to_boundary(
        self,
        line: LineString,
        boundary: Polygon,
    ) -> LineString:
        """Extend a line segment until it meets the boundary on both ends."""
        coords = list(line.coords)
        p1, p2 = Point(coords[0]), Point(coords[-1])

        dx = p2.x - p1.x
        dy = p2.y - p1.y
        length = math.sqrt(dx * dx + dy * dy)

        if length == 0:
            return line

        dx, dy = dx / length, dy / length

        max_extent = 100000

        extended_p1 = Point(p1.x - dx * max_extent, p1.y - dy * max_extent)
        extended_p2 = Point(p2.x + dx * max_extent, p2.y + dy * max_extent)

        extended = LineString([extended_p1, extended_p2])

        clipped = extended.intersection(boundary)

        return clipped if clipped.geom_type == "LineString" else line

    def calculate_outputs(
        self,
        parsed: dict[str, Any],
        spatial: dict[str, Any],
        query: str,
    ) -> list[CalculationOutput]:
        """Determine and perform calculations based on query keywords.

        Args:
            parsed: Parsed drawing objects
            spatial: Spatial analysis results
            query: User query to determine needed calculations

        Returns:
            List of calculation outputs
        """
        query_lower = query.lower()
        results: list[CalculationOutput] = []

        if self._needs_area_calculation(query_lower):
            results.extend(self._perform_area_calculations(parsed, spatial))

        if self._needs_distance_calculation(query_lower):
            results.extend(self._perform_distance_calculations(parsed, spatial))

        if self._needs_extension_calculation(query_lower):
            results.extend(self._perform_extension_calculations(parsed, spatial))

        if self._needs_width_calculation(query_lower):
            results.extend(self._perform_width_calculations(parsed, spatial))

        return results

    def _needs_area_calculation(self, query: str) -> bool:
        keywords = ["area", "size", "square", "coverage", "50%", "curtilage"]
        return any(kw in query for kw in keywords)

    def _needs_distance_calculation(self, query: str) -> bool:
        keywords = ["distance", "from boundary", "metres from", "within", "how far"]
        return any(kw in query for kw in keywords)

    def _needs_extension_calculation(self, query: str) -> bool:
        keywords = ["extension", "depth", "project", "extend", "rear", "beyond"]
        return any(kw in query for kw in keywords)

    def _needs_width_calculation(self, query: str) -> bool:
        keywords = ["width", "wide", "half", "side"]
        return any(kw in query for kw in keywords)

    def _perform_area_calculations(
        self,
        parsed: dict[str, Any],
        spatial: dict[str, Any],
    ) -> list[CalculationOutput]:
        results = []

        plot_boundary = parsed.get("plot_boundary")
        walls = parsed.get("walls", [])

        if plot_boundary:
            area_result = self.calculate_polygon_area(
                list(plot_boundary.exterior.coords)
            )
            results.append(
                CalculationOutput(
                    calculation_type="area",
                    value=area_result["area"],
                    unit="m2",
                    description="Plot boundary (curtilage) area",
                )
            )

        if walls:
            combined = unary_union(walls)
            building_area = combined.area * self.MM2_TO_M2
            results.append(
                CalculationOutput(
                    calculation_type="area",
                    value=round(building_area, 2),
                    unit="m2",
                    description="Total building footprint area",
                )
            )

        if plot_boundary and walls:
            coverage = self.calculate_curtilage_coverage(
                plot_boundary=plot_boundary,
                buildings=walls,
                original_house=spatial.get("original_footprint"),
            )
            results.append(
                CalculationOutput(
                    calculation_type="ratio",
                    value=coverage["coverage_percent"],
                    unit="%",
                    description=f"Building coverage ({coverage['coverage_percent']}% of curtilage)",
                    details=coverage,
                )
            )

        return results

    def _perform_distance_calculations(
        self,
        parsed: dict[str, Any],
        spatial: dict[str, Any],
    ) -> list[CalculationOutput]:
        results = []

        walls = parsed.get("walls", [])
        plot_boundary = parsed.get("plot_boundary")

        if walls and plot_boundary:
            combined = unary_union(walls)
            dist_result = self.calculate_min_distance_to_boundary(
                building=combined,
                boundary=plot_boundary,
            )

            results.append(
                CalculationOutput(
                    calculation_type="distance",
                    value=dist_result["min_distance_m"],
                    unit="m",
                    description="Minimum distance from building to plot boundary",
                )
            )

            if dist_result["within_2m"]:
                results.append(
                    CalculationOutput(
                        calculation_type="flag",
                        value=1,
                        unit="boolean",
                        description="Building is within 2m of boundary (eaves height limit applies)",
                    )
                )

        return results

    def _perform_extension_calculations(
        self,
        parsed: dict[str, Any],
        spatial: dict[str, Any],
    ) -> list[CalculationOutput]:
        results = []

        rear_wall = spatial.get("rear_wall")
        extensions = parsed.get("extensions", [])

        if rear_wall and extensions:
            for i, ext in enumerate(extensions):
                depth_result = self.calculate_extension_depth(
                    extension=ext,
                    rear_wall=rear_wall,
                )

                results.append(
                    CalculationOutput(
                        calculation_type="length",
                        value=depth_result["depth_m"],
                        unit="m",
                        description=f"Extension {i + 1} depth beyond rear wall",
                    )
                )

        return results

    def _perform_width_calculations(
        self,
        parsed: dict[str, Any],
        spatial: dict[str, Any],
    ) -> list[CalculationOutput]:
        results = []

        original = spatial.get("original_footprint")

        if original:
            width_result = self.calculate_building_width(original)
            results.append(
                CalculationOutput(
                    calculation_type="length",
                    value=width_result["width_m"],
                    unit="m",
                    description="Original house width",
                )
            )

            results.append(
                CalculationOutput(
                    calculation_type="length",
                    value=round(width_result["width_m"] / 2, 2),
                    unit="m",
                    description="Maximum allowed side extension width (50% of original)",
                )
            )

        return results
