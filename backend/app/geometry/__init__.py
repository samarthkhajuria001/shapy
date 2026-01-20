"""Geometry engine package for compliance calculations."""

from app.geometry.calculator import GeometryCalculator
from app.geometry.spatial_inference import (
    DrawingParser,
    OriginalHouseDetector,
    SpatialInferenceEngine,
)
from app.geometry.types import (
    CalculationOutput,
    ExtensionType,
    HighwayAnalysis,
    HouseType,
    LandType,
    RoofType,
    SpatialAnalysisResult,
)

__all__ = [
    "CalculationOutput",
    "DrawingParser",
    "ExtensionType",
    "GeometryCalculator",
    "HighwayAnalysis",
    "HouseType",
    "LandType",
    "OriginalHouseDetector",
    "RoofType",
    "SpatialAnalysisResult",
    "SpatialInferenceEngine",
]
