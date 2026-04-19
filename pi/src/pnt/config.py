from __future__ import annotations

import os
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
    cam1_id: int = 2
    cam0_label: str = "servo"
    cam1_label: str = "fixed_down"
    width: int = 640
    height: int = 480
    poll_interval_s: float = 0.03
    up_fov_deg: float = 70.0
    down_fov_deg: float = 90.0
    down_camera_yaw_offset_deg: float = 0.0


@dataclass
class StereoConfig:
    baseline_m: float = 0.12
    orb_feature_count: int = 1600
    match_ratio_test: float = 0.78
    min_match_count: int = 24
    vertical_tolerance_px: float = 24.0
    min_disparity_px: float = 1.5
    max_disparity_px: float = 220.0
    center_window_fraction: float = 0.55


@dataclass
class VisualOdometryConfig:
    max_corners: int = 400
    quality_level: float = 0.01
    min_distance_px: float = 7.0
    lk_win_size_px: int = 21
    lk_max_level: int = 3
    fb_max_error_px: float = 1.5
    ransac_reproj_threshold_px: float = 3.0
    min_track_count: int = 28
    max_rotation_mismatch_deg: float = 18.0
    max_tilt_change_deg: float = 8.0
    max_step_m_per_frame: float = 8.0


@dataclass
class MapCollectionConfig:
    collections_root: Path = field(default_factory=lambda: Path(__file__).resolve().parents[3] / "dash" / "data" / "collections")
    active_collection_id: str | None = None
    matcher_mode: str = "classical"
    use_runtime_embeddings: bool = False
    embedding_model_name: str = "facebook/dinov3-vitl16-pretrain-sat493m"
    embedding_device: str = "auto"
    retrieval_top_k: int = 5
    candidate_search_limit: int = 16
    seed_search_radius_m: float = 1609.34
    retrieval_min_score: float = 0.30
    retrieval_min_gap: float = 0.02
    orb_feature_count: int = 1200
    match_ratio_test: float = 0.75
    ransac_reproj_threshold_px: float = 5.0
    verify_min_inliers: int = 12
    verify_min_inlier_ratio: float = 0.20
    verify_min_structural_score: float = 0.16
    edge_weight: float = 0.22
    canny_low_threshold: int = 50
    canny_high_threshold: int = 140
    corner_max_count: int = 300
    corner_quality_level: float = 0.01
    corner_min_distance_px: float = 7.0
    down_camera_fov_deg: float = 90.0
    subtile_search_enabled: bool = True
    subtile_top_tile_count: int = 3
    subtile_scale_factors: tuple[float, ...] = (0.85, 1.0, 1.2)
    subtile_min_size_px: int = 96


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
    enable_celestial: bool = False
    mission_bounds: MissionBounds = field(default_factory=MissionBounds)
    camera: CameraConfig = field(default_factory=CameraConfig)
    stereo: StereoConfig = field(default_factory=StereoConfig)
    vo: VisualOdometryConfig = field(default_factory=VisualOdometryConfig)
    maps: MapCollectionConfig = field(default_factory=MapCollectionConfig)
    udp_host: str = field(default_factory=lambda: os.getenv("NATSEC_UDP_HOST", "127.0.0.1"))
    udp_port: int = field(default_factory=lambda: int(os.getenv("NATSEC_UDP_PORT", "10110")))
    debug_udp_enabled: bool = field(default_factory=lambda: os.getenv("NATSEC_DEBUG_UDP_ENABLED", "1") not in {"0", "false", "False"})
    debug_udp_port: int = field(default_factory=lambda: int(os.getenv("NATSEC_DEBUG_UDP_PORT", "10111")))
