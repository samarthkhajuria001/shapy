"""Type definitions for the geometry engine.

Contains enums and data classes used throughout the geometry module.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from shapely.geometry import LineString, Polygon


class HouseType(str, Enum):
    """Types of dwelling for regulation lookup."""

    DETACHED = "detached"
    SEMI_DETACHED = "semi-detached"
    TERRACED = "terraced"
    END_TERRACE = "end-terrace"


class LandType(str, Enum):
    """Types of land classification affecting permitted development."""

    STANDARD = "standard"
    ARTICLE_2_3 = "article_2_3"
    SSSI = "sssi"


class ExtensionType(str, Enum):
    """Types of building extensions."""

    REAR_SINGLE = "rear_single"
    REAR_MULTI = "rear_multi"
    SIDE = "side"
    LOFT = "loft"
    PORCH = "porch"
    OUTBUILDING = "outbuilding"


class RoofType(str, Enum):
    """Types of roof for outbuilding height limits."""

    DUAL_PITCHED = "dual_pitched"
    FLAT = "flat"
    OTHER = "other"


@dataclass
class HighwayAnalysis:
    """Analysis results for a single highway segment."""

    highway: LineString
    distance_to_boundary: float
    facing_wall_length: float
    has_door: bool
    score: float


@dataclass
class SpatialAnalysisResult:
    """Complete spatial analysis of a drawing."""

    principal_wall: Optional[LineString] = None
    principal_direction: Optional[str] = None
    highway_distance: Optional[float] = None
    fronting_angle: Optional[float] = None
    confidence: float = 0.0
    requires_clarification: bool = False
    clarification_reason: Optional[str] = None

    rear_wall: Optional[LineString] = None
    distance_from_principal: Optional[float] = None
    is_stepped: bool = False

    is_l_shaped: bool = False
    fill_ratio: float = 1.0

    original_footprint: Optional[Polygon] = None
    extensions: list = field(default_factory=list)
    detection_method: Optional[str] = None

    party_walls: list = field(default_factory=list)
    buildable_sides: list = field(default_factory=lambda: ["left", "right"])

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "principal_direction": self.principal_direction,
            "highway_distance_m": round(self.highway_distance / 1000, 2) if self.highway_distance else None,
            "fronting_angle": self.fronting_angle,
            "confidence": self.confidence,
            "requires_clarification": self.requires_clarification,
            "clarification_reason": self.clarification_reason,
            "distance_from_principal_m": round(self.distance_from_principal / 1000, 2) if self.distance_from_principal else None,
            "is_stepped": self.is_stepped,
            "is_l_shaped": self.is_l_shaped,
            "fill_ratio": round(self.fill_ratio, 2),
            "detection_method": self.detection_method,
            "buildable_sides": self.buildable_sides,
            "extension_count": len(self.extensions),
        }


@dataclass
class CalculationOutput:
    """Result from a geometric calculation."""

    calculation_type: str
    value: float
    unit: str
    description: str
    details: dict[str, Any] = field(default_factory=dict)
