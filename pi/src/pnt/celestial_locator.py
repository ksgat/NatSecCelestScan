from __future__ import annotations

from .config import MissionBounds
from .models import Attitude, CelestialLocationResult, StarSolveResult


class CelestialLocator:
    def __init__(self, bounds: MissionBounds) -> None:
        self._bounds = bounds

    def locate(self, star_solution: StarSolveResult, attitude: Attitude, seed_lat: float, seed_lon: float) -> CelestialLocationResult:
        if not star_solution.valid:
            return CelestialLocationResult(valid=False)
        center_lat = (self._bounds.min_lat + self._bounds.max_lat) / 2.0
        center_lon = (self._bounds.min_lon + self._bounds.max_lon) / 2.0
        d_lat = abs(seed_lat - center_lat)
        d_lon = abs(seed_lon - center_lon)
        proximity = max(0.0, 1.0 - (d_lat + d_lon) * 500.0)
        attitude_residual = abs(attitude.yaw - star_solution.roll_deg) * 0.1
        confidence = max(0.0, min(1.0, 0.6 * star_solution.confidence + 0.4 * proximity))
        return CelestialLocationResult(
            valid=confidence >= 0.65,
            lat=center_lat,
            lon=center_lon,
            position_error_m=max(5.0, 100.0 * (1.0 - confidence)),
            attitude_residual_deg=attitude_residual,
            search_score=confidence,
            ambiguity_score=max(0.0, 1.0 - confidence),
            confidence=confidence,
        )

