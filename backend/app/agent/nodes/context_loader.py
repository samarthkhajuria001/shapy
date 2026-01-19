"""Context loader node for extracting drawing data from session."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from redis.asyncio import Redis

from app.config import get_settings
from app.agent.state import (
    AgentState,
    DesignatedLandType,
    DrawingContext,
    HouseType,
    add_reasoning_step,
)
from app.repositories.session_repository import SessionRepository

logger = logging.getLogger(__name__)


UNIT_CONVERSIONS = {
    "mm": {"to_m": 0.001, "to_sqm": 0.000001},
    "cm": {"to_m": 0.01, "to_sqm": 0.0001},
    "m": {"to_m": 1.0, "to_sqm": 1.0},
    "in": {"to_m": 0.0254, "to_sqm": 0.00064516},
    "ft": {"to_m": 0.3048, "to_sqm": 0.092903},
}


def _convert_to_metres(value: float, unit: str) -> float | None:
    """Convert a length value to metres. Returns None for unknown units."""
    unit_lower = unit.lower()
    if unit_lower in UNIT_CONVERSIONS:
        return value * UNIT_CONVERSIONS[unit_lower]["to_m"]
    return None


def _convert_to_sqm(value: float, unit: str) -> float | None:
    """Convert an area value to square metres. Returns None for unknown units."""
    unit_lower = unit.lower()
    if unit_lower in UNIT_CONVERSIONS:
        return value * UNIT_CONVERSIONS[unit_lower]["to_sqm"]
    return None


def _extract_measurements_from_objects(
    objects: list[dict[str, Any]],
    metadata: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract basic measurements from drawing objects.

    This provides rough estimates. Phase 5 Calculator will provide
    precise measurements using Shapely.
    """
    measurements: dict[str, Any] = {}
    coord_unit = metadata.get("coordinate_unit", "mm")

    if coord_unit.lower() not in UNIT_CONVERSIONS:
        logger.warning(f"Unknown coordinate unit '{coord_unit}', skipping measurements")
        measurements["unit_warning"] = f"Unknown unit: {coord_unit}"
        return measurements

    bounding_box = metadata.get("bounding_box")
    if bounding_box:
        width = bounding_box.get("max_x", 0) - bounding_box.get("min_x", 0)
        height = bounding_box.get("max_y", 0) - bounding_box.get("min_y", 0)

        width_m = _convert_to_metres(width, coord_unit)
        height_m = _convert_to_metres(height, coord_unit)

        if width_m is not None and height_m is not None:
            measurements["bounding_width_m"] = width_m
            measurements["bounding_height_m"] = height_m

    plot_area = None
    building_area = None

    for obj in objects:
        layer = obj.get("layer", "").lower()
        obj_type = obj.get("type")

        if obj_type == "POLYLINE" and obj.get("closed"):
            points = obj.get("points", [])
            if len(points) >= 3:
                area_raw = _calculate_polygon_area(points)
                area_sqm = _convert_to_sqm(area_raw, coord_unit)

                if area_sqm is None:
                    continue

                if "plot" in layer or "boundary" in layer or "curtilage" in layer:
                    if plot_area is None or area_sqm > plot_area:
                        plot_area = area_sqm
                elif "wall" in layer or "building" in layer or "house" in layer:
                    if building_area is None:
                        building_area = area_sqm
                    else:
                        building_area += area_sqm

    if plot_area:
        measurements["plot_area_sqm"] = round(plot_area, 2)
    if building_area:
        measurements["building_footprint_sqm"] = round(building_area, 2)

    return measurements


def _calculate_polygon_area(points: list[tuple[float, float]]) -> float:
    """Calculate polygon area using shoelace formula."""
    n = len(points)
    if n < 3:
        return 0.0

    area = 0.0
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]

    return abs(area) / 2.0


def _parse_user_metadata(
    session_meta: dict[str, Any],
    context_meta: dict[str, Any],
) -> dict[str, Any]:
    """
    Extract user-provided metadata from session.

    This includes answers to clarification questions stored in the session.
    """
    user_data: dict[str, Any] = {}

    for key in ["house_type", "is_original_house", "prior_extensions_sqm",
                "designated_land_type", "article_4_direction"]:
        if key in session_meta:
            user_data[key] = session_meta[key]
        if key in context_meta:
            user_data[key] = context_meta[key]

    if "house_type" in user_data:
        try:
            user_data["house_type"] = HouseType(user_data["house_type"]).value
        except ValueError:
            pass

    if "designated_land_type" in user_data:
        try:
            user_data["designated_land_type"] = DesignatedLandType(
                user_data["designated_land_type"]
            ).value
        except ValueError:
            pass

    return user_data


async def context_loader_node(
    state: AgentState,
    redis_client: Redis | None = None,
) -> dict[str, Any]:
    """
    Load drawing context from session into agent state.

    Args:
        state: Current agent state with session_id
        redis_client: Redis client for session access

    Returns:
        State updates with drawing_context populated
    """
    session_id = state.get("session_id", "")

    if not session_id:
        logger.warning("No session_id in state")
        return {
            "drawing_context": DrawingContext(
                session_id="",
                has_drawing=False,
            ).model_dump(),
            "reasoning_chain": add_reasoning_step(state, "No session ID provided"),
        }

    if redis_client is None:
        from app.infrastructure.redis import get_redis
        try:
            redis_client = get_redis()
        except RuntimeError:
            logger.error("Redis not initialized")
            return {
                "drawing_context": DrawingContext(
                    session_id=session_id,
                    has_drawing=False,
                ).model_dump(),
                "errors": state.get("errors", []) + ["Redis connection unavailable"],
                "reasoning_chain": add_reasoning_step(state, "Redis unavailable"),
            }

    settings = get_settings()
    ttl_seconds = settings.session_ttl_hours * 3600
    repo = SessionRepository(redis_client, ttl_seconds)

    session_meta = await repo.get_meta(session_id)
    if session_meta is None:
        logger.info(f"Session not found: {session_id}")
        return {
            "drawing_context": DrawingContext(
                session_id=session_id,
                has_drawing=False,
            ).model_dump(),
            "reasoning_chain": add_reasoning_step(
                state,
                f"Session {session_id[:8]}... not found or expired",
            ),
        }

    context_data = await repo.get_context(session_id)

    if context_data is None:
        logger.debug(f"No drawing context in session: {session_id}")
        return {
            "drawing_context": DrawingContext(
                session_id=session_id,
                has_drawing=False,
            ).model_dump(),
            "reasoning_chain": add_reasoning_step(
                state,
                "Session found but no drawing uploaded",
            ),
        }

    objects = context_data.get("objects", [])
    metadata = context_data.get("metadata", {})

    measurements = _extract_measurements_from_objects(objects, metadata)
    user_metadata = _parse_user_metadata(session_meta, metadata)

    drawing_context = DrawingContext(
        session_id=session_id,
        has_drawing=True,
        plot_area_sqm=measurements.get("plot_area_sqm"),
        building_footprint_sqm=measurements.get("building_footprint_sqm"),
        layers_present=metadata.get("layers_present", []),
        **user_metadata,
    )

    object_count = metadata.get("object_count", len(objects))
    layers = metadata.get("layers_present", [])

    reasoning = f"Loaded drawing: {object_count} objects, {len(layers)} layers"
    if measurements.get("plot_area_sqm"):
        reasoning += f", {measurements['plot_area_sqm']}m2 plot"
    if measurements.get("building_footprint_sqm"):
        reasoning += f", {measurements['building_footprint_sqm']}m2 building"

    logger.debug(f"Loaded context for session {session_id}: {reasoning}")

    return {
        "drawing_context": drawing_context.model_dump(),
        "reasoning_chain": add_reasoning_step(state, reasoning),
    }


async def update_context_from_clarification(
    state: AgentState,
    field_name: str,
    value: Any,
    redis_client: Redis | None = None,
) -> dict[str, Any]:
    """
    Update drawing context with user-provided clarification.

    Args:
        state: Current agent state
        field_name: DrawingContext field to update
        value: Value from user's clarification response
        redis_client: Redis client for persisting updates

    Returns:
        State updates with modified drawing_context
    """
    ctx_dict = state.get("drawing_context") or {}

    valid_fields = {
        "house_type", "is_original_house", "prior_extensions_sqm",
        "designated_land_type", "article_4_direction",
        "year_of_prior_extension",
    }

    if field_name not in valid_fields:
        logger.warning(f"Invalid field for clarification update: {field_name}")
        return {}

    ctx_dict[field_name] = value

    if redis_client and ctx_dict.get("session_id"):
        settings = get_settings()
        ttl_seconds = settings.session_ttl_hours * 3600
        repo = SessionRepository(redis_client, ttl_seconds)
        await repo.update_meta(ctx_dict["session_id"], **{field_name: value})

    return {
        "drawing_context": ctx_dict,
        "reasoning_chain": add_reasoning_step(
            state,
            f"Updated {field_name} from clarification response",
        ),
    }
