"""Drawing object validation schemas."""

import math
from typing import Literal, Any

from pydantic import BaseModel, Field, field_validator, model_validator


class LineObject(BaseModel):
    """LINE drawing object with start and end points."""

    type: Literal["LINE"]
    layer: str = Field(..., min_length=1)
    start: tuple[float, float]
    end: tuple[float, float]

    @field_validator("layer")
    @classmethod
    def layer_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("layer cannot be empty or whitespace")
        return v.strip()

    @field_validator("start", "end", mode="before")
    @classmethod
    def validate_point(cls, v: Any) -> tuple[float, float]:
        if not isinstance(v, (list, tuple)):
            raise ValueError("point must be an array [x, y]")
        if len(v) != 2:
            raise ValueError(f"point must have exactly 2 coordinates, got {len(v)}")

        try:
            x, y = float(v[0]), float(v[1])
        except (TypeError, ValueError) as e:
            raise ValueError(f"coordinates must be numbers: {e}")

        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("coordinates must be finite numbers (not NaN or Infinity)")

        return (x, y)


class PolylineObject(BaseModel):
    """POLYLINE drawing object with array of points."""

    type: Literal["POLYLINE"]
    layer: str = Field(..., min_length=1)
    points: list[tuple[float, float]] = Field(..., min_length=2)
    closed: bool = False

    @field_validator("layer")
    @classmethod
    def layer_not_whitespace(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("layer cannot be empty or whitespace")
        return v.strip()

    @field_validator("points", mode="before")
    @classmethod
    def validate_points(cls, v: Any) -> list[tuple[float, float]]:
        if not isinstance(v, list):
            raise ValueError("points must be an array")
        if len(v) < 2:
            raise ValueError(f"points must have at least 2 coordinates, got {len(v)}")

        validated = []
        for i, point in enumerate(v):
            if not isinstance(point, (list, tuple)):
                raise ValueError(f"point[{i}] must be an array [x, y]")
            if len(point) != 2:
                raise ValueError(f"point[{i}] must have exactly 2 coordinates, got {len(point)}")

            try:
                x, y = float(point[0]), float(point[1])
            except (TypeError, ValueError) as e:
                raise ValueError(f"point[{i}] coordinates must be numbers: {e}")

            if not (math.isfinite(x) and math.isfinite(y)):
                raise ValueError(f"point[{i}] coordinates must be finite (not NaN or Infinity)")

            validated.append((x, y))

        return validated


DrawingObject = LineObject | PolylineObject

VALID_TYPES = {"LINE", "POLYLINE"}


def validate_single_object(obj: dict, index: int) -> tuple[dict | None, list[str], list[str]]:
    """
    Validate a single drawing object.

    Returns:
        (validated_dict, warnings, errors)
        - validated_dict is None if validation failed
        - warnings are non-fatal issues
        - errors are fatal issues
    """
    warnings = []
    errors = []

    if not isinstance(obj, dict):
        errors.append(f"object[{index}]: must be a dict, got {type(obj).__name__}")
        return None, warnings, errors

    obj_type = obj.get("type")
    if obj_type not in VALID_TYPES:
        errors.append(f"object[{index}]: invalid type '{obj_type}', must be one of {VALID_TYPES}")
        return None, warnings, errors

    try:
        if obj_type == "LINE":
            validated = LineObject.model_validate(obj)
        else:
            validated = PolylineObject.model_validate(obj)

        validated_dict = validated.model_dump()

        # Check for warnings
        layer = validated_dict.get("layer", "")
        if obj_type == "POLYLINE":
            if layer == "Plot Boundary" and not validated_dict.get("closed"):
                warnings.append(f"object[{index}]: Plot Boundary should be a closed polygon")
            if validated_dict.get("closed") and len(validated_dict.get("points", [])) < 3:
                warnings.append(f"object[{index}]: closed polyline should have at least 3 points to form a polygon")

        return validated_dict, warnings, errors

    except Exception as e:
        error_msg = str(e)
        if hasattr(e, "errors"):
            error_details = "; ".join(
                f"{'.'.join(str(x) for x in err.get('loc', []))}: {err.get('msg', '')}"
                for err in e.errors()
            )
            error_msg = error_details
        errors.append(f"object[{index}]: {error_msg}")
        return None, warnings, errors


def validate_drawing_objects(
    objects: list[Any],
    max_objects: int = 100,
    max_points_per_polyline: int = 500,
    max_layers: int = 25,
) -> tuple[list[dict], list[str], list[str]]:
    """
    Validate a list of drawing objects.

    Args:
        objects: List of raw drawing object dicts
        max_objects: Maximum allowed objects
        max_points_per_polyline: Maximum points per polyline
        max_layers: Maximum unique layers allowed

    Returns:
        (validated_objects, all_warnings, all_errors)
        - If all_errors is non-empty, validation failed
        - validated_objects contains only successfully validated objects
    """
    all_warnings = []
    all_errors = []
    validated_objects = []

    if not isinstance(objects, list):
        all_errors.append("objects must be an array")
        return [], all_warnings, all_errors

    if len(objects) > max_objects:
        all_errors.append(f"too many objects: {len(objects)} (max {max_objects})")
        return [], all_warnings, all_errors

    unique_layers: set[str] = set()
    for obj in objects:
        if isinstance(obj, dict):
            layer = obj.get("layer")
            if layer and isinstance(layer, str):
                unique_layers.add(layer)

    if len(unique_layers) > max_layers:
        all_errors.append(f"too many unique layers: {len(unique_layers)} (max {max_layers})")
        return [], all_warnings, all_errors

    for i, obj in enumerate(objects):
        # Check polyline point limit before full validation
        if isinstance(obj, dict) and obj.get("type") == "POLYLINE":
            points = obj.get("points", [])
            if isinstance(points, list) and len(points) > max_points_per_polyline:
                all_errors.append(
                    f"object[{i}]: polyline has {len(points)} points (max {max_points_per_polyline})"
                )
                continue

        validated, warnings, errors = validate_single_object(obj, i)

        all_warnings.extend(warnings)
        all_errors.extend(errors)

        if validated is not None:
            validated_objects.append(validated)

    # Global warnings
    layers = {obj.get("layer") for obj in validated_objects}
    if "Plot Boundary" not in layers and validated_objects:
        all_warnings.append("No 'Plot Boundary' layer found - some calculations may not work")

    return validated_objects, all_warnings, all_errors
