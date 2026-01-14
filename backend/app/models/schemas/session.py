"""Session and context request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class BoundingBox(BaseModel):
    """Bounding box for drawing coordinates."""

    min_x: float
    min_y: float
    max_x: float
    max_y: float


class ContextMetadata(BaseModel):
    """Metadata generated from drawing context."""

    uploaded_at: datetime
    object_count: int
    coordinate_unit: str = "mm"
    context_version: int
    layers_present: list[str]
    layer_counts: dict[str, int]
    has_plot_boundary: bool
    plot_boundary_closed: bool
    bounding_box: BoundingBox | None = None


class SessionCreateResponse(BaseModel):
    """Response when creating a new session."""

    session_id: str
    created_at: datetime


class SessionStatusResponse(BaseModel):
    """Full session status including context info."""

    session_id: str
    user_id: str
    created_at: datetime
    updated_at: datetime | None = None
    expires_at: datetime
    has_context: bool
    context_metadata: ContextMetadata | None = None


class ContextUpdateRequest(BaseModel):
    """Request body for updating drawing context."""

    objects: list[Any] = Field(
        ...,
        description="Array of drawing objects (LINE or POLYLINE)",
    )


class ContextUpdateResponse(BaseModel):
    """Response after updating drawing context."""

    object_count: int
    layers: list[str]
    layer_counts: dict[str, int]
    warnings: list[str]
    updated_at: datetime


class ContextGetResponse(BaseModel):
    """Response when retrieving drawing context."""

    objects: list[dict[str, Any]]
    metadata: ContextMetadata


class SessionListItem(BaseModel):
    """Summary of a single session for listing."""

    session_id: str
    created_at: datetime
    updated_at: datetime | None = None
    has_context: bool
    object_count: int = 0


class SessionListResponse(BaseModel):
    """Response containing list of user sessions."""

    sessions: list[SessionListItem]
    count: int
