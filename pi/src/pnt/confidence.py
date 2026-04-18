from __future__ import annotations

from .models import CelestialLocationResult, ConfidenceResult, GeoMatchResult, TerrainResult, VisualOdometryResult


class ConfidenceFusion:
    def compute(
        self,
        vo: VisualOdometryResult,
        geo: GeoMatchResult,
        celestial: CelestialLocationResult,
        terrain: TerrainResult,
        last_absolute_fix_age_s: float,
    ) -> ConfidenceResult:
        terrain_adjust = {
            "snow": -0.2,
            "water": -0.2,
            "urban": 0.1,
            "vegetation": 0.0,
            "unknown": -0.05,
        }.get(terrain.terrain_class, -0.05)
        if geo.valid:
            score = min(1.0, geo.confidence + terrain_adjust * 0.25)
            return ConfidenceResult(score, 1, "geo_match")
        if celestial.valid:
            score = min(1.0, celestial.confidence + 0.05)
            return ConfidenceResult(score, 2, "celestial_fallback")
        decay = max(0.1, 1.0 - last_absolute_fix_age_s / 60.0)
        score = max(0.0, min(1.0, vo.confidence * decay + terrain_adjust))
        return ConfidenceResult(score, 6 if vo.valid else 0, "visual_odometry" if vo.valid else "invalid")

