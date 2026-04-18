from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MissionBounds:
    min_lat: float = 37.0
    max_lat: float = 37.01
    min_lon: float = -122.01
    max_lon: float = -122.0


@dataclass
class CameraConfig:
    cam0_id: int = 0
    cam1_id: int = 1
    up_fov_deg: float = 70.0
    down_fov_deg: float = 90.0


@dataclass
class NavConfig:
    root_dir: Path = field(default_factory=lambda: Path(__file__).resolve().parents[1])
    loop_hz: float = 5.0
    celestial_retry_seconds: float = 10.0
    degraded_timeout_seconds: float = 5.0
    geo_match_min_confidence: float = 0.7
    vo_min_confidence: float = 0.5
    celestial_min_confidence: float = 0.65
    sky_min_star_candidates: int = 12
    min_seconds_between_flips: float = 3.0
    mission_bounds: MissionBounds = field(default_factory=MissionBounds)
    camera: CameraConfig = field(default_factory=CameraConfig)
    udp_host: str = "127.0.0.1"
    udp_port: int = 10110

