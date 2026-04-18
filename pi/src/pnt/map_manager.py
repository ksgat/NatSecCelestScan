from __future__ import annotations

from pathlib import Path

from .config import MissionBounds


class MapManager:
    def __init__(self, root: Path, bounds: MissionBounds) -> None:
        self._root = root
        self._bounds = bounds
        self._tiles_dir = root / "maps"

    def query_candidate_tiles(self, lat: float, lon: float) -> list[dict[str, object]]:
        return [
            {
                "path": str(self._tiles_dir / "mission_tile.png"),
                "lat_center": lat,
                "lon_center": lon,
                "source": "cached",
                "meters_per_pixel": 0.5,
            }
        ]

    @property
    def bounds(self) -> MissionBounds:
        return self._bounds

