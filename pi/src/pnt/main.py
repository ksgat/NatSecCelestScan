from __future__ import annotations

import math
import time

from .camera import CameraCapture
from .confidence import ConfidenceFusion
from .config import NavConfig
from .embedding_backend import build_embedding_backend
from .geo_match import GeoMatcher
from .imu import ImuInterface
from .map_manager import MapManager
from .models import CelestialLocationResult, NavContext, NavMode, PoseEstimate, TerrainResult
from .nmea_output import format_gpgga, format_gprmc
from .servo import ServoController
from .stereo.stereo_depth import StereoDepthEstimator
from .visual_odometry import VisualOdometry
from comms.udp_tx import UdpTransmitter
from edge.terrain_classifier import TerrainClassifier


class NavigationSystem:
    def __init__(self, config: NavConfig | None = None) -> None:
        self.config = config or NavConfig()
        self.config.maps.matcher_mode = "classical"
        self.config.maps.use_runtime_embeddings = False
        self.config.maps.down_camera_fov_deg = self.config.camera.down_fov_deg
        self.context = NavContext()
        self.servo = ServoController(min_seconds_between_flips=self.config.min_seconds_between_flips)
        self.imu = ImuInterface()
        self.cam0 = CameraCapture(
            camera_id=self.config.camera.cam0_id,
            label=self.config.camera.cam0_label,
            width=self.config.camera.width,
            height=self.config.camera.height,
            poll_interval_s=self.config.camera.poll_interval_s,
        )
        self.cam1 = CameraCapture(
            camera_id=self.config.camera.cam1_id,
            label=self.config.camera.cam1_label,
            width=self.config.camera.width,
            height=self.config.camera.height,
            poll_interval_s=self.config.camera.poll_interval_s,
        )
        self.sky_assessor = None
        self.stereo = StereoDepthEstimator(self.config.camera, self.config.stereo)
        self.vo = VisualOdometry(self.config.camera, self.config.vo)
        self.embedding_backend = build_embedding_backend(
            self.config.maps.embedding_model_name,
            self.config.maps.embedding_device,
            enabled=self.config.maps.use_runtime_embeddings,
        )
        self.maps = MapManager(self.config.root_dir, self.config.mission_bounds, self.config.maps)
        self.geo = GeoMatcher(self.maps, self.embedding_backend, self.config.maps)
        if self.config.enable_celestial:
            from .celestial.star_solver import StarSolver
            from .celestial_locator import CelestialLocator
            from .sky_assessor import SkyAssessor

            self.sky_assessor = SkyAssessor(self.config)
            star_solver_config = self.config.root_dir / "assets" / "config" / "star_solver.json"
            self.star_solver = StarSolver.from_config(star_solver_config)
            self.celestial = CelestialLocator(self.config.mission_bounds)
        else:
            self.star_solver = None
            self.celestial = None
        self.confidence = ConfidenceFusion()
        self.terrain = TerrainClassifier()
        self.tx = UdpTransmitter(self.config.udp_host, self.config.udp_port)
        self.debug_tx = UdpTransmitter(self.config.udp_host, self.config.debug_udp_port)
        center_lat = (self.config.mission_bounds.min_lat + self.config.mission_bounds.max_lat) / 2.0
        center_lon = (self.config.mission_bounds.min_lon + self.config.mission_bounds.max_lon) / 2.0
        self.context.pose = PoseEstimate(center_lat, center_lon, 0.0, 0.0, 0.0, "init")
        self._last_absolute_fix_time = time.time()
        self._last_celestial_attempt = 0.0

    def start(self) -> None:
        self.cam0.start()
        self.cam1.start()
        self.imu.start()
        self.terrain.start()
        self.servo.set_position("DOWN")

    def stop(self) -> None:
        self.terrain.stop()
        self.imu.stop()
        self.cam0.stop()
        self.cam1.stop()
        self.servo.cleanup()
        self.tx.close()
        self.debug_tx.close()

    def tick(self, cam0_down_frame=None, cam1_frame=None, cam0_up_frame=None) -> dict[str, object]:
        now = time.time()
        assert self.context.pose is not None
        if cam0_down_frame is None and cam0_up_frame is None:
            live_cam0 = self.cam0.get_frame()
            if self.servo.get_position() == "UP":
                cam0_up_frame = live_cam0
            else:
                cam0_down_frame = live_cam0
        if cam1_frame is None:
            cam1_frame = self.cam1.get_frame()
        attitude = self.imu.get_attitude()
        depth = self.stereo.update(cam0_down_frame, cam1_frame, attitude)
        altitude_hint_m = depth.altitude_m if depth.valid else self.context.pose.alt_m
        vo = self.vo.update(cam1_frame, attitude, altitude_hint_m, now)
        geo = self.geo.update(cam1_frame, altitude_hint_m, attitude, self.context.pose.lat, self.context.pose.lon)
        terrain = self.terrain.get_latest_result()
        celestial = self._maybe_run_celestial(now, cam0_up_frame, terrain)
        confidence = self.confidence.compute(vo, geo, celestial, terrain, now - self._last_absolute_fix_time)
        altitude_m = altitude_hint_m

        if geo.valid:
            self.context.mode = NavMode.GEO_MATCH
            self.context.pose = PoseEstimate(geo.lat, geo.lon, altitude_m, geo.heading_deg, confidence.confidence, "geo_match")
            self._last_absolute_fix_time = now
        elif celestial.valid:
            self.context.mode = NavMode.CELESTIAL_FALLBACK
            self.context.pose = PoseEstimate(celestial.lat, celestial.lon, altitude_m, attitude.yaw, confidence.confidence, "celestial_fallback")
            self._last_absolute_fix_time = now
        elif vo.valid:
            self.context.mode = NavMode.VISUAL_ODOMETRY
            next_lat, next_lon = self._offset_latlon(
                self.context.pose.lat,
                self.context.pose.lon,
                delta_east_m=vo.delta_position_m[0],
                delta_north_m=vo.delta_position_m[1],
            )
            self.context.pose.lat = next_lat
            self.context.pose.lon = next_lon
            self.context.pose.alt_m = altitude_m
            self.context.pose.heading_deg = attitude.yaw
            self.context.pose.confidence = confidence.confidence
            self.context.pose.fix_type = "visual_odometry"
        else:
            self.context.mode = NavMode.DEGRADED_IMU
            self.context.pose.heading_deg = attitude.yaw
            self.context.pose.alt_m = altitude_m
            self.context.pose.confidence = confidence.confidence
            self.context.pose.fix_type = "degraded_imu"

        gga = format_gpgga(self.context.pose, confidence.fix_quality)
        rmc = format_gprmc(self.context.pose, valid=confidence.fix_quality != 0)
        self.tx.transmit(gga)
        self.tx.transmit(rmc)

        self.context.loop_counter += 1
        self.context.last_absolute_fix_age_s = now - self._last_absolute_fix_time
        self.context.debug = {
            "mode": self.context.mode.value,
            "vo_confidence": vo.confidence,
            "geo_confidence": geo.confidence,
            "celestial_confidence": celestial.confidence,
            "terrain": terrain.terrain_class,
            "map_collection": self.maps.active_collection_id or "",
            "runtime_embeddings": self.config.maps.use_runtime_embeddings,
            "embedding_backend": self.embedding_backend.status().model_name,
            "embedding_backend_ok": self.embedding_backend.status().available,
            "cam0_ok": self.cam0.status().ok,
            "cam1_ok": self.cam1.status().ok,
            "cam0_fps": round(self.cam0.status().fps, 2),
            "cam1_fps": round(self.cam1.status().fps, 2),
            "gga": gga,
            "rmc": rmc,
        }
        if self.config.debug_udp_enabled:
            self.debug_tx.transmit_json(
                self._build_debug_packet(
                    now=now,
                    attitude=attitude,
                    depth=depth,
                    vo=vo,
                    geo=geo,
                    celestial=celestial,
                    terrain=terrain,
                    confidence=confidence,
                    gga=gga,
                    rmc=rmc,
                )
            )
        return self.context.debug

    def _maybe_run_celestial(self, now: float, cam0_up_frame, terrain: TerrainResult):
        assert self.context.pose is not None
        if not self.config.enable_celestial or self.celestial is None or self.star_solver is None or self.sky_assessor is None:
            return CelestialLocationResult(False)
        stale_fix = now - self._last_absolute_fix_time > self.config.degraded_timeout_seconds
        retry_open = now - self._last_celestial_attempt > self.config.celestial_retry_seconds
        terrain_poor = terrain.terrain_class in {"snow", "water", "unknown"}
        if not (stale_fix and retry_open and terrain_poor):
            return self.celestial.locate(self.star_solver.empty_result(), self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        _, previous_ts = self.cam0.get_frame_with_timestamp()
        if self.servo.flip_camera("UP") != "UP":
            return self.celestial.locate(self.star_solver.empty_result(), self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        if cam0_up_frame is None:
            cam0_up_frame = self._wait_for_cam0_frame(min_timestamp=previous_ts)
        assessment = self.sky_assessor.assess(cam0_up_frame)
        self._last_celestial_attempt = now
        if not assessment.usable_for_stars:
            self.servo.flip_camera("DOWN")
            return self.celestial.locate(self.star_solver.empty_result(), self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        star_solution = self.star_solver.solve(cam0_up_frame)
        result = self.celestial.locate(star_solution, self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        self.servo.flip_camera("DOWN")
        return result

    def _wait_for_cam0_frame(self, timeout_s: float = 1.5, min_timestamp: float = 0.0):
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            frame, ts = self.cam0.get_frame_with_timestamp()
            if frame is not None and ts > min_timestamp:
                return frame
            time.sleep(0.02)
        return None

    @staticmethod
    def _offset_latlon(lat_deg: float, lon_deg: float, *, delta_east_m: float, delta_north_m: float) -> tuple[float, float]:
        delta_lat = delta_north_m / 111320.0
        cos_lat = max(1e-6, abs(math.cos(math.radians(lat_deg))))
        delta_lon = delta_east_m / (111320.0 * cos_lat)
        return lat_deg + delta_lat, lon_deg + delta_lon

    def _build_debug_packet(self, *, now: float, attitude, depth, vo, geo, celestial, terrain, confidence, gga: str, rmc: str) -> dict[str, object]:
        assert self.context.pose is not None
        imu_reading = self.imu.get_reading()
        cam0_status = self.cam0.status()
        cam1_status = self.cam1.status()
        return {
            "type": "nav_debug",
            "ts": now,
            "mode": self.context.mode.value,
            "last_absolute_fix_age_s": self.context.last_absolute_fix_age_s,
            "pose": {
                "lat": self.context.pose.lat,
                "lon": self.context.pose.lon,
                "alt_m": self.context.pose.alt_m,
                "heading_deg": self.context.pose.heading_deg,
                "confidence": self.context.pose.confidence,
                "fix_type": self.context.pose.fix_type,
            },
            "attitude": {
                "roll": attitude.roll,
                "pitch": attitude.pitch,
                "yaw": attitude.yaw,
            },
            "imu": {
                "ax": imu_reading.ax,
                "ay": imu_reading.ay,
                "az": imu_reading.az,
                "gx": imu_reading.gx,
                "gy": imu_reading.gy,
                "gz": imu_reading.gz,
                "temp": imu_reading.temp,
                "timestamp": imu_reading.timestamp,
            },
            "stereo": {
                "valid": depth.valid,
                "altitude_m": depth.altitude_m,
                "center_depth_m": depth.center_depth_m,
                "disparity_confidence": depth.disparity_confidence,
                "depth_variance": depth.depth_variance,
            },
            "vo": {
                "valid": vo.valid,
                "confidence": vo.confidence,
                "track_count": vo.track_count,
                "inlier_ratio": vo.inlier_ratio,
                "parallax_score": vo.parallax_score,
                "reprojection_error": vo.reprojection_error,
            },
            "geo": {
                "valid": geo.valid,
                "verified": geo.verified,
                "confidence": geo.confidence,
                "candidate_count": geo.candidate_count,
                "inlier_count": geo.inlier_count,
                "structural_score": geo.structural_score,
                "match_score": geo.match_score,
                "tile_path": geo.tile_path,
            },
            "celestial": {
                "valid": celestial.valid,
                "confidence": celestial.confidence,
                "method": celestial.method,
            },
            "terrain": {
                "terrain_class": terrain.terrain_class,
                "confidence": terrain.confidence,
                "inference_ms": terrain.inference_ms,
            },
            "confidence": {
                "confidence": confidence.confidence,
                "fix_quality": confidence.fix_quality,
                "fix_type": confidence.fix_type,
            },
            "camera": {
                "cam0": {
                    "camera_id": cam0_status.camera_id,
                    "label": cam0_status.label,
                    "ok": cam0_status.ok,
                    "error": cam0_status.error,
                    "fps": cam0_status.fps,
                    "frame_timestamp": cam0_status.frame_timestamp,
                },
                "cam1": {
                    "camera_id": cam1_status.camera_id,
                    "label": cam1_status.label,
                    "ok": cam1_status.ok,
                    "error": cam1_status.error,
                    "fps": cam1_status.fps,
                    "frame_timestamp": cam1_status.frame_timestamp,
                },
                "servo_position": self.servo.get_position(),
            },
            "map": {
                "collection_id": self.maps.active_collection_id or "",
                "runtime_embeddings": self.config.maps.use_runtime_embeddings,
                "embedding_backend": self.embedding_backend.status().model_name,
                "embedding_backend_ok": self.embedding_backend.status().available,
            },
            "nmea": {
                "gga": gga,
                "rmc": rmc,
            },
        }


def main() -> None:
    nav = NavigationSystem()
    nav.start()
    try:
        period = 1.0 / nav.config.loop_hz
        while True:
            nav.tick()
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        nav.stop()


if __name__ == "__main__":
    main()
