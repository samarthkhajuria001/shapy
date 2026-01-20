"""Spatial inference engine for semantic interpretation of drawing geometry."""

import math
from typing import Any, Optional

from shapely.geometry import LineString, MultiLineString, Point, Polygon
from shapely.ops import linemerge, polygonize, snap, unary_union

from app.geometry.types import (
    HighwayAnalysis,
    HouseType,
    SpatialAnalysisResult,
)


class SpatialInferenceEngine:
    """Infers semantic meaning from raw geometry (principal elevation, rear wall, etc)."""

    def analyze(
        self,
        walls: list[Polygon],
        plot_boundary: Optional[Polygon],
        highways: list[LineString],
        doors: Optional[list[LineString]] = None,
        windows: Optional[list[LineString]] = None,
        session_metadata: Optional[dict] = None,
    ) -> SpatialAnalysisResult:
        """Perform complete spatial analysis of drawing."""
        result = SpatialAnalysisResult()
        meta = session_metadata or {}

        if not walls:
            result.requires_clarification = True
            result.clarification_reason = "No building walls found in drawing"
            return result

        principal = self.identify_principal_elevation(
            walls=walls,
            highway_lines=highways,
            plot_boundary=plot_boundary,
            doors=doors,
        )

        result.principal_wall = principal.get("principal_wall")
        result.principal_direction = principal.get("principal_direction")
        result.highway_distance = principal.get("highway_distance")
        result.fronting_angle = principal.get("fronting_angle")
        result.confidence = principal.get("confidence", 0.5)
        result.requires_clarification = principal.get("requires_clarification", False)
        result.clarification_reason = principal.get("clarification_reason")

        if result.principal_wall:
            rear = self.identify_rear_wall(walls, principal)
            result.rear_wall = rear.get("rear_wall")
            result.distance_from_principal = rear.get("distance_from_front")
            result.is_stepped = rear.get("is_stepped", False)

        l_shape = self.detect_l_shaped_building(walls)
        result.is_l_shaped = l_shape.get("is_l_shaped", False)
        result.fill_ratio = l_shape.get("fill_ratio", 1.0)

        house_type = meta.get("house_type")
        if house_type and plot_boundary:
            party = self.identify_party_walls(
                walls=walls,
                plot_boundary=plot_boundary,
                house_type=house_type,
                doors=doors,
                windows=windows,
            )
            result.party_walls = party.get("party_walls", [])
            result.buildable_sides = party.get("buildable_sides", ["left", "right"])

        detector = OriginalHouseDetector(walls, meta)
        detection = detector.detect()
        result.original_footprint = detection.get("original_footprint")
        result.extensions = detection.get("extensions", [])
        result.detection_method = detection.get("detection_method")

        return result

    def identify_principal_elevation(
        self,
        walls: list[Polygon],
        highway_lines: list[LineString],
        plot_boundary: Optional[Polygon],
        doors: Optional[list[LineString]] = None,
    ) -> dict[str, Any]:
        """Identify principal elevation (front of house facing highway)."""
        if not highway_lines:
            if plot_boundary and walls:
                result = self._infer_front_from_plot_geometry(plot_boundary, walls)
                result["confidence"] = 0.5
                result["requires_clarification"] = True
                result["clarification_reason"] = "No highway found in drawing"
                return result
            return {
                "principal_wall": None,
                "confidence": 0.0,
                "requires_clarification": True,
                "clarification_reason": "No highway or plot boundary found",
            }

        all_wall_segments = self._extract_all_wall_segments(walls)
        highway_analyses = []

        for highway in highway_lines:
            analysis = self._analyze_highway(
                highway, plot_boundary, all_wall_segments, doors
            )
            highway_analyses.append(analysis)

        highway_analyses.sort(key=lambda x: x.score, reverse=True)

        if len(highway_analyses) >= 2:
            top_two = highway_analyses[:2]
            score_ratio = top_two[1].score / max(top_two[0].score, 0.001)

            if score_ratio > 0.7:
                if top_two[0].has_door and not top_two[1].has_door:
                    primary_highway = top_two[0].highway
                    confidence = 0.85
                    requires_clarification = False
                    clarification_reason = None
                elif top_two[1].has_door and not top_two[0].has_door:
                    primary_highway = top_two[1].highway
                    confidence = 0.85
                    requires_clarification = False
                    clarification_reason = None
                else:
                    primary_highway = top_two[0].highway
                    confidence = 0.4
                    requires_clarification = True
                    clarification_reason = (
                        f"Corner plot detected. Please confirm which road your front door faces."
                    )
            else:
                primary_highway = top_two[0].highway
                confidence = 0.9
                requires_clarification = False
                clarification_reason = None
        else:
            primary_highway = highway_analyses[0].highway
            confidence = 0.95
            requires_clarification = False
            clarification_reason = None

        candidate_walls = self._find_fronting_walls(all_wall_segments, primary_highway)

        if candidate_walls:
            best = max(
                candidate_walls,
                key=lambda w: (1 / max(w["distance"], 1)) * (45 - w["angle"]),
            )

            return {
                "principal_wall": best["segment"],
                "principal_direction": self._vector_to_cardinal(
                    self._segment_to_vector(best["segment"])
                ),
                "highway_distance": best["distance"],
                "fronting_angle": best["angle"],
                "confidence": confidence,
                "requires_clarification": requires_clarification,
                "clarification_reason": clarification_reason,
            }

        if plot_boundary and walls:
            result = self._infer_front_from_plot_geometry(plot_boundary, walls)
            result["confidence"] = 0.3
            result["requires_clarification"] = True
            result["clarification_reason"] = "No wall clearly fronts the highway"
            return result

        return {"principal_wall": None, "confidence": 0.0}

    def identify_rear_wall(
        self,
        walls: list[Polygon],
        principal_elevation: dict[str, Any],
    ) -> dict[str, Any]:
        """Identify rear wall as the wall opposite to principal elevation."""
        principal_direction = principal_elevation.get("principal_direction")
        principal_wall = principal_elevation.get("principal_wall")

        if not principal_direction or not principal_wall:
            return {"rear_wall": None, "error": "No principal elevation identified"}

        opposite_direction = {
            "north": "south",
            "south": "north",
            "east": "west",
            "west": "east",
        }.get(principal_direction)

        combined_building = unary_union(walls)
        all_segments = self._extract_segments(combined_building)

        rear_candidates = []
        for segment in all_segments:
            segment_direction = self._vector_to_cardinal(
                self._segment_to_vector(segment)
            )

            if segment_direction == opposite_direction:
                dist = segment.distance(principal_wall)
                rear_candidates.append(
                    {
                        "segment": segment,
                        "distance_from_front": dist,
                        "direction": segment_direction,
                    }
                )

        if rear_candidates:
            best = max(
                rear_candidates,
                key=lambda r: r["segment"].length * r["distance_from_front"],
            )
            is_stepped = (
                len([r for r in rear_candidates if r["segment"].length > 1000]) > 1
            )
            return {
                "rear_wall": best["segment"],
                "distance_from_front": best["distance_from_front"],
                "is_stepped": is_stepped,
            }

        return {"rear_wall": None, "error": "Could not identify rear wall"}

    def detect_l_shaped_building(self, walls: list[Polygon]) -> dict[str, Any]:
        """Detect if the building footprint is L-shaped."""
        if not walls:
            return {"is_l_shaped": False, "fill_ratio": 1.0}

        combined = unary_union(walls)
        actual_area = combined.area
        bounding_box = combined.minimum_rotated_rectangle
        bbox_area = bounding_box.area

        if bbox_area == 0:
            return {"is_l_shaped": False, "fill_ratio": 1.0}

        fill_ratio = actual_area / bbox_area

        if fill_ratio < 0.75:
            return {
                "is_l_shaped": True,
                "fill_ratio": fill_ratio,
            }

        return {"is_l_shaped": False, "fill_ratio": fill_ratio}

    def identify_party_walls(
        self,
        walls: list[Polygon],
        plot_boundary: Polygon,
        house_type: str,
        doors: Optional[list[LineString]] = None,
        windows: Optional[list[LineString]] = None,
    ) -> dict[str, Any]:
        """Identify party walls (shared walls with neighbours)."""
        if house_type not in ["semi-detached", "terraced", "end-terrace"]:
            return {
                "party_walls": [],
                "buildable_sides": ["left", "right"],
                "confidence": 1.0,
                "requires_clarification": False,
            }

        combined_building = unary_union(walls)
        building_segments = self._extract_segments(combined_building)

        boundary_coincident_walls = []
        tolerance = 100

        for segment in building_segments:
            dist_to_boundary = segment.distance(plot_boundary.exterior)
            if dist_to_boundary < tolerance:
                boundary_coincident_walls.append(segment)

        potential_party_walls = []
        for wall in boundary_coincident_walls:
            has_opening = False

            if doors:
                for door in doors:
                    if wall.distance(door) < 500:
                        has_opening = True
                        break

            if not has_opening and windows:
                for window in windows:
                    if wall.distance(window) < 500:
                        has_opening = True
                        break

            if not has_opening:
                potential_party_walls.append(wall)

        expected_count = {"semi-detached": 1, "end-terrace": 1, "terraced": 2}.get(
            house_type, 0
        )

        if len(potential_party_walls) == expected_count:
            confidence = 0.9
            requires_clarification = False
            clarification_reason = None
        else:
            confidence = 0.5
            requires_clarification = True
            clarification_reason = (
                f"Detected {len(potential_party_walls)} potential party walls "
                f"for {house_type} (expected {expected_count}). "
                f"Please confirm which side(s) are attached to neighbours."
            )

        buildable_sides = ["left", "right"]
        for wall in potential_party_walls:
            side = self._determine_wall_side(wall, combined_building)
            if side in buildable_sides:
                buildable_sides.remove(side)

        return {
            "party_walls": potential_party_walls,
            "buildable_sides": buildable_sides,
            "confidence": confidence,
            "requires_clarification": requires_clarification,
            "clarification_reason": clarification_reason,
        }

    def _analyze_highway(
        self,
        highway: LineString,
        plot_boundary: Optional[Polygon],
        wall_segments: list[LineString],
        doors: Optional[list[LineString]],
    ) -> HighwayAnalysis:
        """Score a highway to determine if it's the main highway."""
        distance_to_boundary = (
            plot_boundary.distance(highway) if plot_boundary else float("inf")
        )

        facing_wall_length = 0.0
        for segment in wall_segments:
            if self._wall_faces_highway(segment, highway):
                facing_wall_length += segment.length

        has_door = False
        if doors:
            for door in doors:
                door_center = door.centroid
                if highway.distance(door_center) < 10000:
                    has_door = True
                    break

        score = (
            facing_wall_length * 1.0
            + (50000 if has_door else 0)
            + (10000 / max(distance_to_boundary, 100))
        )

        return HighwayAnalysis(
            highway=highway,
            distance_to_boundary=distance_to_boundary,
            facing_wall_length=facing_wall_length,
            has_door=has_door,
            score=score,
        )

    def _wall_faces_highway(
        self, wall_segment: LineString, highway: LineString
    ) -> bool:
        wall_vector = self._segment_to_vector(wall_segment)
        highway_vector = self._segment_to_vector(highway)
        angle = self._angle_between_vectors(wall_vector, highway_vector)
        perpendicular_angle = abs(90 - angle)
        return perpendicular_angle < 45

    def _find_fronting_walls(
        self, wall_segments: list[LineString], highway: LineString
    ) -> list[dict]:
        candidates = []
        highway_vector = self._segment_to_vector(highway)

        for segment in wall_segments:
            wall_vector = self._segment_to_vector(segment)
            angle = self._angle_between_vectors(wall_vector, highway_vector)
            perpendicular_angle = abs(90 - angle)

            if perpendicular_angle < 45:
                distance_to_highway = segment.distance(highway)
                candidates.append(
                    {
                        "segment": segment,
                        "angle": perpendicular_angle,
                        "distance": distance_to_highway,
                    }
                )

        return candidates

    def _extract_all_wall_segments(self, walls: list[Polygon]) -> list[LineString]:
        segments = []
        for wall_polygon in walls:
            coords = list(wall_polygon.exterior.coords)
            for i in range(len(coords) - 1):
                segment = LineString([coords[i], coords[i + 1]])
                segments.append(segment)
        return segments

    def _extract_segments(self, geometry) -> list[LineString]:
        segments = []
        if geometry.geom_type == "Polygon":
            coords = list(geometry.exterior.coords)
            for i in range(len(coords) - 1):
                segments.append(LineString([coords[i], coords[i + 1]]))
        elif geometry.geom_type == "MultiPolygon":
            for poly in geometry.geoms:
                segments.extend(self._extract_segments(poly))
        return segments

    def _infer_front_from_plot_geometry(
        self, plot_boundary: Polygon, walls: list[Polygon]
    ) -> dict[str, Any]:
        coords = list(plot_boundary.exterior.coords)
        edges = []
        for i in range(len(coords) - 1):
            edge = LineString([coords[i], coords[i + 1]])
            avg_y = (coords[i][1] + coords[i + 1][1]) / 2
            edges.append({"edge": edge, "avg_y": avg_y})

        front_edge = min(edges, key=lambda e: e["avg_y"])

        combined_building = unary_union(walls)
        building_segments = self._extract_segments(combined_building)

        closest_wall = min(
            building_segments, key=lambda s: s.distance(front_edge["edge"])
        )

        return {
            "principal_wall": closest_wall,
            "principal_direction": "south",
            "highway_distance": None,
            "fronting_angle": 0,
            "inference_method": "geometric_fallback",
        }

    def _segment_to_vector(self, segment: LineString) -> tuple[float, float]:
        coords = list(segment.coords)
        return (coords[1][0] - coords[0][0], coords[1][1] - coords[0][1])

    def _vector_to_cardinal(self, vector: tuple[float, float]) -> str:
        angle = math.atan2(vector[1], vector[0]) * 180 / math.pi
        if -45 <= angle < 45:
            return "east"
        elif 45 <= angle < 135:
            return "north"
        elif angle >= 135 or angle < -135:
            return "west"
        else:
            return "south"

    def _angle_between_vectors(
        self, v1: tuple[float, float], v2: tuple[float, float]
    ) -> float:
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.sqrt(v1[0] ** 2 + v1[1] ** 2)
        mag2 = math.sqrt(v2[0] ** 2 + v2[1] ** 2)
        if mag1 == 0 or mag2 == 0:
            return 0
        cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
        return math.acos(cos_angle) * 180 / math.pi

    def _determine_wall_side(self, wall_segment: LineString, building: Polygon) -> str:
        centroid = building.centroid
        wall_center = wall_segment.centroid
        if wall_center.x < centroid.x:
            return "left"
        return "right"


class OriginalHouseDetector:
    """Attempts to distinguish original house from extensions."""

    def __init__(self, walls: list, session_metadata: dict):
        self.walls = walls
        self.metadata = session_metadata

    def detect(self) -> dict[str, Any]:
        """Detect original house vs extensions."""
        explicit_result = self._check_layer_names()
        if explicit_result.get("found"):
            return explicit_result

        return self._geometric_decomposition()

    def _check_layer_names(self) -> dict[str, Any]:
        """Check for explicit layer naming indicating extensions."""
        original_polygons = []
        extension_polygons = []

        for wall in self.walls:
            if isinstance(wall, dict):
                layer = wall.get("layer", "").lower()
                polygon = self._to_polygon(wall)
            else:
                layer = ""
                polygon = wall

            if any(ext in layer for ext in ["extension", "proposed", "new"]):
                if polygon:
                    extension_polygons.append(polygon)
            else:
                if polygon:
                    original_polygons.append(polygon)

        if extension_polygons:
            return {
                "found": True,
                "original_footprint": (
                    unary_union(original_polygons) if original_polygons else None
                ),
                "extensions": extension_polygons,
                "detection_method": "layer_names",
                "confidence": 0.9,
            }

        return {"found": False}

    def _geometric_decomposition(self) -> dict[str, Any]:
        """Use geometric heuristics when no explicit labeling exists."""
        polygons = []
        for wall in self.walls:
            if isinstance(wall, Polygon):
                polygons.append(wall)
            elif isinstance(wall, dict):
                poly = self._to_polygon(wall)
                if poly:
                    polygons.append(poly)

        if not polygons:
            return {
                "found": False,
                "original_footprint": None,
                "extensions": [],
                "detection_method": "none",
                "confidence": 0.0,
            }

        combined = unary_union(polygons)
        original_estimate = self._find_main_rectangular_mass(combined)

        extension_parts = []
        if original_estimate:
            potential_extensions = combined.difference(original_estimate)
            if not potential_extensions.is_empty:
                if potential_extensions.geom_type == "MultiPolygon":
                    extension_parts = list(potential_extensions.geoms)
                elif potential_extensions.geom_type == "Polygon":
                    extension_parts = [potential_extensions]

        return {
            "found": True,
            "original_footprint": original_estimate,
            "extensions": extension_parts,
            "detection_method": "geometric_heuristic",
            "confidence": 0.6,
        }

    def _find_main_rectangular_mass(self, building) -> Optional[Polygon]:
        """Find the largest approximately rectangular region."""
        if building.is_empty:
            return None

        bounds = building.bounds
        best_rect = None
        best_area = 0

        for width_factor in [1.0, 0.9, 0.8, 0.7, 0.6]:
            for height_factor in [1.0, 0.9, 0.8, 0.7, 0.6]:
                rect = self._make_rect(bounds, width_factor, height_factor)
                intersection = rect.intersection(building)
                coverage = intersection.area / rect.area if rect.area > 0 else 0

                if coverage > 0.9 and rect.area > best_area:
                    best_area = rect.area
                    best_rect = rect

        return best_rect if best_rect else building.convex_hull

    def _make_rect(
        self,
        bounds: tuple,
        width_factor: float,
        height_factor: float,
    ) -> Polygon:
        minx, miny, maxx, maxy = bounds
        width = (maxx - minx) * width_factor
        height = (maxy - miny) * height_factor
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2

        return Polygon(
            [
                (cx - width / 2, cy - height / 2),
                (cx + width / 2, cy - height / 2),
                (cx + width / 2, cy + height / 2),
                (cx - width / 2, cy + height / 2),
            ]
        )

    def _to_polygon(self, wall: dict) -> Optional[Polygon]:
        """Convert a wall dict to a Shapely Polygon."""
        if isinstance(wall, Polygon):
            return wall

        obj_type = wall.get("type")
        if obj_type == "POLYLINE" and wall.get("closed"):
            points = wall.get("points", [])
            if len(points) >= 3:
                coords = [(p[0], p[1]) for p in points]
                return Polygon(coords)
        return None


class DrawingParser:
    """Parse raw drawing objects into Shapely geometries."""

    def parse(self, objects: list[dict]) -> dict[str, Any]:
        """Convert raw drawing objects to Shapely geometries."""
        walls = []
        plot_boundary = None
        highways = []
        extensions = []
        doors = []
        windows = []

        layer_lines: dict[str, list[LineString]] = {}

        for obj in objects:
            layer = obj.get("layer", "").lower()
            obj_type = obj.get("type")

            if obj_type == "POLYLINE" and obj.get("closed"):
                points = [(p[0], p[1]) for p in obj.get("points", [])]
                if len(points) >= 3:
                    polygon = Polygon(points)

                    if "plot" in layer or "boundary" in layer:
                        plot_boundary = polygon
                    elif "extension" in layer:
                        extensions.append(polygon)
                    elif "wall" in layer:
                        walls.append(polygon)

            elif obj_type == "LINE" or (
                obj_type == "POLYLINE" and not obj.get("closed")
            ):
                if obj_type == "LINE":
                    points = [tuple(obj["start"]), tuple(obj["end"])]
                else:
                    points = [(p[0], p[1]) for p in obj.get("points", [])]

                if len(points) >= 2:
                    line = LineString(points)

                    if "highway" in layer or "road" in layer:
                        highways.append(line)
                    elif "door" in layer:
                        doors.append(line)
                    elif "window" in layer:
                        windows.append(line)
                    else:
                        if layer not in layer_lines:
                            layer_lines[layer] = []
                        layer_lines[layer].append(line)

        for layer, lines in layer_lines.items():
            if len(lines) >= 3:
                polygon = self._try_polygonize_lines(lines)
                if polygon and polygon.is_valid:
                    if "plot" in layer or "boundary" in layer:
                        if plot_boundary is None:
                            plot_boundary = polygon
                    elif "wall" in layer:
                        walls.append(polygon)

        return {
            "walls": walls,
            "plot_boundary": plot_boundary,
            "highways": highways,
            "extensions": extensions,
            "doors": doors,
            "windows": windows,
        }

    def _try_polygonize_lines(
        self, lines: list[LineString], snap_tolerance: float = 50.0
    ) -> Optional[Polygon]:
        """Attempt to create a polygon from line segments."""
        if len(lines) < 3:
            return None

        try:
            multi = MultiLineString(lines)

            snapped_lines = []
            for line in lines:
                snapped = snap(line, multi, snap_tolerance)
                if snapped.geom_type == "LineString":
                    snapped_lines.append(snapped)

            merged = linemerge(snapped_lines)
            polygons = list(polygonize(merged))

            if polygons:
                return max(polygons, key=lambda p: p.area)

            if merged.geom_type == "LineString" and merged.is_ring:
                return Polygon(merged)

        except Exception:
            pass

        return None
