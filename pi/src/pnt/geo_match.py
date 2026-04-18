from __future__ import annotations

from .map_manager import MapManager
from .models import Attitude, GeoMatchResult

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class GeoMatcher:
    def __init__(self, map_manager: MapManager) -> None:
        self._map_manager = map_manager

    def update(self, frame, altitude_m: float, attitude: Attitude, seed_lat: float, seed_lon: float) -> GeoMatchResult:
        if frame is None or np is None:
            return self._invalid(seed_lat, seed_lon, attitude.yaw)
        arr = np.asarray(frame)
        texture = float(arr.std() / 64.0)
        confidence = max(0.0, min(1.0, texture))
        inlier_count = int(texture * 100)
        scale_error = max(0.0, 1.0 - min(1.0, altitude_m / 100.0))
        valid = confidence >= 0.7 and inlier_count >= 30
        tiles = self._map_manager.query_candidate_tiles(seed_lat, seed_lon)
        source = str(tiles[0]["source"]) if tiles else "cached"
        return GeoMatchResult(valid, seed_lat, seed_lon, attitude.yaw, confidence, inlier_count, scale_error, confidence, source)

    @staticmethod
    def _invalid(lat: float, lon: float, heading: float) -> GeoMatchResult:
        return GeoMatchResult(False, lat, lon, heading, 0.0, 0, 1.0, 0.0, "cached")

