"""Geometry engine package for Shapy compliance calculations.

Provides geometric calculations, spatial inference, and rule evaluation
for UK Permitted Development Rights compliance checking.
"""

from app.geometry.types import HouseType, LandType
from app.geometry.calculator import GeometryCalculator
from app.geometry.spatial_inference import SpatialInferenceEngine
from app.geometry.rules import RuleRegistry, ComplianceRule

__all__ = [
    "HouseType",
    "LandType",
    "GeometryCalculator",
    "SpatialInferenceEngine",
    "RuleRegistry",
    "ComplianceRule",
]
