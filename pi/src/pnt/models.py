from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class NavMode(str, Enum):
    ACQUIRING = "ACQUIRING"
    VISUAL_ODOMETRY = "VISUAL_ODOMETRY"
    GEO_MATCH = "GEO_MATCH"
    CELESTIAL_FALLBACK = "CELESTIAL_FALLBACK"
    DEGRADED_IMU = "DEGRADED_IMU"


@dataclass
class PoseEstimate:
    lat: float
    lon: float
    alt_m: float
    heading_deg: float
    confidence: float
    fix_type: str


@dataclass
class ImuReading:
    ax: float = 0.0
    ay: float = 0.0
    az: float = 9.81
    gx: float = 0.0
    gy: float = 0.0
    gz: float = 0.0
    temp: float = 20.0
    timestamp: float = 0.0


@dataclass
class Attitude:
    roll: float = 0.0
    pitch: float = 0.0
    yaw: float = 0.0


@dataclass
class StereoDepthResult:
    valid: bool
    altitude_m: float
    disparity_confidence: float
    center_depth_m: float
    depth_variance: float


@dataclass
class VisualOdometryResult:
    valid: bool
    delta_position_m: tuple[float, float, float]
    delta_yaw_deg: float
    velocity_mps: tuple[float, float, float]
    track_count: int
    inlier_ratio: float
    parallax_score: float
    reprojection_error: float
    feature_quality: float
    confidence: float


@dataclass
class GeoMatchResult:
    valid: bool
    lat: float
    lon: float
    heading_deg: float
    match_score: float
    inlier_count: int
    scale_error: float
    confidence: float
    source: str = "cached"
    candidate_count: int = 0
    verified: bool = False
    structural_score: float = 0.0
    tile_path: str = ""


@dataclass
class MapTileCandidate:
    collection_id: str
    path: Path
    zoom: int
    x: int
    y: int
    north: float
    south: float
    east: float
    west: float
    lat_center: float
    lon_center: float
    meters_per_pixel: float
    embedding_score: float
    distance_m: float = 0.0
    source: str = "cached"


@dataclass
class SkyAssessment:
    usable_for_sun: bool
    usable_for_stars: bool
    sky_fraction: float
    brightness: float
    saturation_fraction: float
    star_candidate_count: int
    occlusion_score: float
    confidence: float


@dataclass
class StarSolveResult:
    valid: bool
    ra_deg: float = 0.0
    dec_deg: float = 0.0
    roll_deg: float = 0.0
    fov_deg: float = 0.0
    star_count: int = 0
    residual_px: float = 0.0
    confidence: float = 0.0
    catalog_id_count: int = 0


@dataclass
class CelestialLocationResult:
    valid: bool
    lat: float = 0.0
    lon: float = 0.0
    position_error_m: float = 0.0
    attitude_residual_deg: float = 0.0
    search_score: float = 0.0
    ambiguity_score: float = 1.0
    confidence: float = 0.0
    method: str = "bounded_star_fallback"


@dataclass
class TerrainResult:
    terrain_class: str
    confidence: float
    inference_ms: float


@dataclass
class ConfidenceResult:
    confidence: float
    fix_quality: int
    fix_type: str


@dataclass
class NavContext:
    mode: NavMode = NavMode.ACQUIRING
    pose: Optional[PoseEstimate] = None
    last_absolute_fix_age_s: float = 0.0
    ground_poor_since_s: float = 0.0
    loop_counter: int = 0
    debug: dict[str, object] = field(default_factory=dict)
