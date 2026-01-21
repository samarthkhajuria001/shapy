"""Session service for business logic."""

import json
from datetime import datetime, timezone, timedelta
from typing import Any

from redis.asyncio import Redis

from app.config import Settings
from app.core.exceptions import (
    ContextTooLargeError,
    InvalidDrawingObjectError,
    MaxSessionsError,
    SessionNotFoundError,
    SessionOwnershipError,
)
from app.models.schemas.drawing import validate_drawing_objects
from app.models.schemas.session import (
    BoundingBox,
    ContextGetResponse,
    ContextMetadata,
    ContextUpdateResponse,
    MessageItem,
    MessagesResponse,
    SessionCreateResponse,
    SessionListItem,
    SessionListResponse,
    SessionStatusResponse,
)
from app.repositories.session_repository import SessionRepository


class SessionService:
    """Business logic for session and context management."""

    def __init__(self, redis: Redis, settings: Settings):
        self.settings = settings
        ttl_seconds = settings.session_ttl_hours * 3600
        self.repo = SessionRepository(redis, ttl_seconds)

    async def create_session(self, user_id: str) -> SessionCreateResponse:
        """Create a new session for user. Raises MaxSessionsError if at limit."""
        current_count = await self.repo.count_user_sessions(user_id)
        if current_count >= self.settings.max_sessions_per_user:
            raise MaxSessionsError(self.settings.max_sessions_per_user)

        meta = await self.repo.create(user_id)
        created_at = datetime.fromisoformat(meta["created_at"])

        return SessionCreateResponse(
            session_id=meta["session_id"],
            created_at=created_at,
        )

    async def get_session(
        self, session_id: str, user_id: str
    ) -> SessionStatusResponse:
        """Get session status. Raises SessionNotFoundError or SessionOwnershipError."""
        meta = await self._get_meta_with_ownership(session_id, user_id)

        ttl = await self.repo.get_ttl(session_id)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl or 0)

        context = await self.repo.get_context(session_id)
        has_context = context is not None
        context_metadata = None

        if context and "metadata" in context:
            context_metadata = self._parse_context_metadata(context["metadata"])

        created_at = datetime.fromisoformat(meta["created_at"])
        updated_at = None
        if meta.get("updated_at"):
            updated_at = datetime.fromisoformat(meta["updated_at"])

        return SessionStatusResponse(
            session_id=meta["session_id"],
            user_id=meta["user_id"],
            created_at=created_at,
            updated_at=updated_at,
            expires_at=expires_at,
            has_context=has_context,
            context_metadata=context_metadata,
        )

    async def list_sessions(self, user_id: str) -> SessionListResponse:
        """List all sessions for a user."""
        sessions = await self.repo.get_user_sessions(user_id)

        items = []
        for session in sessions:
            created_at = datetime.fromisoformat(session["created_at"])
            updated_at = None
            if session.get("updated_at"):
                updated_at = datetime.fromisoformat(session["updated_at"])

            items.append(
                SessionListItem(
                    session_id=session["session_id"],
                    created_at=created_at,
                    updated_at=updated_at,
                    has_context=session.get("has_context", False),
                    object_count=session.get("object_count", 0),
                )
            )

        return SessionListResponse(sessions=items, count=len(items))

    async def update_context(
        self,
        session_id: str,
        user_id: str,
        objects: list[Any],
    ) -> ContextUpdateResponse:
        """
        Update drawing context for session.
        Validates all objects and generates metadata.
        Raises InvalidDrawingObjectError if validation fails.
        Raises ContextTooLargeError if payload exceeds size limit.
        """
        meta = await self._get_meta_with_ownership(session_id, user_id)

        payload_size_bytes = len(json.dumps(objects).encode("utf-8"))
        payload_size_kb = payload_size_bytes / 1024

        if payload_size_kb > self.settings.max_context_size_kb:
            raise ContextTooLargeError(
                f"Context payload too large: {payload_size_kb:.1f}KB "
                f"(max {self.settings.max_context_size_kb}KB)"
            )

        size_warnings = []
        if payload_size_kb > self.settings.context_size_warning_kb:
            size_warnings.append(
                f"Large context payload: {payload_size_kb:.1f}KB "
                f"(consider reducing if performance issues occur)"
            )

        validated_objects, warnings, errors = validate_drawing_objects(
            objects,
            max_objects=self.settings.max_objects_per_context,
            max_points_per_polyline=self.settings.max_points_per_polyline,
            max_layers=self.settings.max_layers_per_context,
        )

        if errors:
            raise InvalidDrawingObjectError(errors)

        context_version = meta.get("context_version", 0) + 1
        metadata = self._generate_metadata(validated_objects, context_version)

        await self.repo.set_context(
            session_id,
            validated_objects,
            metadata,
        )

        return ContextUpdateResponse(
            object_count=metadata["object_count"],
            layers=metadata["layers_present"],
            layer_counts=metadata["layer_counts"],
            warnings=size_warnings + warnings,
            updated_at=datetime.fromisoformat(metadata["uploaded_at"]),
        )

    async def get_context(
        self, session_id: str, user_id: str
    ) -> ContextGetResponse:
        """Get drawing context. Raises SessionNotFoundError if no context."""
        await self._get_meta_with_ownership(session_id, user_id)

        context = await self.repo.get_context(session_id)
        if context is None:
            raise SessionNotFoundError(f"{session_id} (no context)")

        metadata = self._parse_context_metadata(context["metadata"])

        return ContextGetResponse(
            objects=context["objects"],
            metadata=metadata,
        )

    async def delete_session(self, session_id: str, user_id: str) -> bool:
        """Delete session. Returns True if deleted."""
        await self._get_meta_with_ownership(session_id, user_id)
        return await self.repo.delete(session_id, user_id)

    async def get_messages(
        self, session_id: str, user_id: str
    ) -> MessagesResponse:
        """Get chat messages for a session."""
        await self._get_meta_with_ownership(session_id, user_id)

        messages = await self.repo.get_messages(session_id)

        items = []
        for msg in messages:
            timestamp = datetime.fromisoformat(msg["timestamp"])
            items.append(
                MessageItem(
                    id=msg["id"],
                    role=msg["role"],
                    content=msg["content"],
                    timestamp=timestamp,
                    confidence=msg.get("confidence"),
                    query_type=msg.get("query_type"),
                    sources=msg.get("sources"),
                    calculations=msg.get("calculations"),
                    suggested_followups=msg.get("suggested_followups"),
                )
            )

        return MessagesResponse(messages=items, count=len(items))

    async def _get_meta_with_ownership(
        self, session_id: str, user_id: str
    ) -> dict[str, Any]:
        """Get session meta and verify ownership."""
        meta = await self.repo.get_meta(session_id)
        if meta is None:
            raise SessionNotFoundError(session_id)

        if meta.get("user_id") != user_id:
            raise SessionOwnershipError(session_id)

        return meta

    def _generate_metadata(
        self, objects: list[dict[str, Any]], context_version: int
    ) -> dict[str, Any]:
        """Generate full metadata from validated objects."""
        now = datetime.now(timezone.utc)

        layers_present, layer_counts = self._analyze_layers(objects)
        has_plot_boundary, plot_boundary_closed = self._check_plot_boundary(objects)
        bounding_box = self._calculate_bounding_box(objects)

        return {
            "uploaded_at": now.isoformat(),
            "object_count": len(objects),
            "coordinate_unit": "mm",
            "context_version": context_version,
            "layers_present": layers_present,
            "layer_counts": layer_counts,
            "has_plot_boundary": has_plot_boundary,
            "plot_boundary_closed": plot_boundary_closed,
            "bounding_box": bounding_box,
        }

    def _analyze_layers(
        self, objects: list[dict[str, Any]]
    ) -> tuple[list[str], dict[str, int]]:
        """Extract layers and their counts from objects."""
        layer_counts: dict[str, int] = {}
        for obj in objects:
            layer = obj.get("layer", "Unknown")
            layer_counts[layer] = layer_counts.get(layer, 0) + 1

        layers_present = list(layer_counts.keys())
        return layers_present, layer_counts

    def _check_plot_boundary(
        self, objects: list[dict[str, Any]]
    ) -> tuple[bool, bool]:
        """Check if Plot Boundary exists and if it's closed."""
        has_plot_boundary = False
        plot_boundary_closed = False

        for obj in objects:
            if obj.get("layer") == "Plot Boundary":
                has_plot_boundary = True
                if obj.get("type") == "POLYLINE" and obj.get("closed", False):
                    plot_boundary_closed = True
                break

        return has_plot_boundary, plot_boundary_closed

    def _calculate_bounding_box(
        self, objects: list[dict[str, Any]]
    ) -> dict[str, float] | None:
        """Calculate bounding box from all coordinates."""
        if not objects:
            return None

        all_x: list[float] = []
        all_y: list[float] = []

        for obj in objects:
            obj_type = obj.get("type")
            if obj_type == "LINE":
                start = obj.get("start", (0, 0))
                end = obj.get("end", (0, 0))
                all_x.extend([start[0], end[0]])
                all_y.extend([start[1], end[1]])
            elif obj_type == "POLYLINE":
                for point in obj.get("points", []):
                    all_x.append(point[0])
                    all_y.append(point[1])

        if not all_x:
            return None

        return {
            "min_x": min(all_x),
            "min_y": min(all_y),
            "max_x": max(all_x),
            "max_y": max(all_y),
        }

    def _parse_context_metadata(self, meta_dict: dict[str, Any]) -> ContextMetadata:
        """Parse metadata dict into ContextMetadata schema."""
        bounding_box = None
        if meta_dict.get("bounding_box"):
            bounding_box = BoundingBox(**meta_dict["bounding_box"])

        return ContextMetadata(
            uploaded_at=datetime.fromisoformat(meta_dict["uploaded_at"]),
            object_count=meta_dict["object_count"],
            coordinate_unit=meta_dict.get("coordinate_unit", "mm"),
            context_version=meta_dict["context_version"],
            layers_present=meta_dict["layers_present"],
            layer_counts=meta_dict["layer_counts"],
            has_plot_boundary=meta_dict["has_plot_boundary"],
            plot_boundary_closed=meta_dict["plot_boundary_closed"],
            bounding_box=bounding_box,
        )
