from __future__ import annotations

import time

from .celestial.star_solver import StarSolver
from .celestial_locator import CelestialLocator
from .confidence import ConfidenceFusion
from .config import NavConfig
from .geo_match import GeoMatcher
from .imu import ImuInterface
from .map_manager import MapManager
from .models import NavContext, NavMode, PoseEstimate, TerrainResult
from .nmea_output import format_gpgga, format_gprmc
from .servo import ServoController
from .sky_assessor import SkyAssessor
from .stereo.stereo_depth import StereoDepthEstimator
from .visual_odometry import VisualOdometry
from comms.udp_tx import UdpTransmitter
from edge.terrain_classifier import TerrainClassifier


class NavigationSystem:
    def __init__(self, config: NavConfig | None = None) -> None:
        self.config = config or NavConfig()
        self.context = NavContext()
        self.servo = ServoController(self.config.min_seconds_between_flips)
        self.imu = ImuInterface()
        self.sky_assessor = SkyAssessor(self.config)
        self.stereo = StereoDepthEstimator()
        self.vo = VisualOdometry()
        self.maps = MapManager(self.config.root_dir, self.config.mission_bounds)
        self.geo = GeoMatcher(self.maps)
        star_solver_config = self.config.root_dir / "assets" / "config" / "star_solver.json"
        self.star_solver = StarSolver.from_config(star_solver_config)
        self.celestial = CelestialLocator(self.config.mission_bounds)
        self.confidence = ConfidenceFusion()
        self.terrain = TerrainClassifier()
        self.tx = UdpTransmitter(self.config.udp_host, self.config.udp_port)
        center_lat = (self.config.mission_bounds.min_lat + self.config.mission_bounds.max_lat) / 2.0
        center_lon = (self.config.mission_bounds.min_lon + self.config.mission_bounds.max_lon) / 2.0
        self.context.pose = PoseEstimate(center_lat, center_lon, 0.0, 0.0, 0.0, "init")
        self._last_absolute_fix_time = time.time()
        self._last_celestial_attempt = 0.0

    def start(self) -> None:
        self.imu.start()
        self.terrain.start()

    def stop(self) -> None:
        self.terrain.stop()
        self.imu.stop()

    def tick(self, cam0_down_frame=None, cam1_frame=None, cam0_up_frame=None) -> dict[str, object]:
        now = time.time()
        assert self.context.pose is not None
        attitude = self.imu.get_attitude()
        depth = self.stereo.update(cam0_down_frame, cam1_frame)
        vo = self.vo.update(cam0_down_frame, cam1_frame, attitude, now)
        geo = self.geo.update(cam1_frame, depth.altitude_m, attitude, self.context.pose.lat, self.context.pose.lon)
        terrain = self.terrain.get_latest_result()
        celestial = self._maybe_run_celestial(now, cam0_up_frame, terrain)
        confidence = self.confidence.compute(vo, geo, celestial, terrain, now - self._last_absolute_fix_time)

        if geo.valid:
            self.context.mode = NavMode.GEO_MATCH
            self.context.pose = PoseEstimate(geo.lat, geo.lon, depth.altitude_m, geo.heading_deg, confidence.confidence, "geo_match")
            self._last_absolute_fix_time = now
        elif celestial.valid:
            self.context.mode = NavMode.CELESTIAL_FALLBACK
            self.context.pose = PoseEstimate(celestial.lat, celestial.lon, depth.altitude_m, attitude.yaw, confidence.confidence, "celestial_fallback")
            self._last_absolute_fix_time = now
        elif vo.valid:
            self.context.mode = NavMode.VISUAL_ODOMETRY
            self.context.pose.alt_m = depth.altitude_m
            self.context.pose.heading_deg = attitude.yaw
            self.context.pose.confidence = confidence.confidence
            self.context.pose.fix_type = "visual_odometry"
        else:
            self.context.mode = NavMode.DEGRADED_IMU
            self.context.pose.heading_deg = attitude.yaw
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
            "gga": gga,
            "rmc": rmc,
        }
        return self.context.debug

    def _maybe_run_celestial(self, now: float, cam0_up_frame, terrain: TerrainResult):
        assert self.context.pose is not None
        stale_fix = now - self._last_absolute_fix_time > self.config.degraded_timeout_seconds
        retry_open = now - self._last_celestial_attempt > self.config.celestial_retry_seconds
        terrain_poor = terrain.terrain_class in {"snow", "water", "unknown"}
        if not (stale_fix and retry_open and terrain_poor):
            return self.celestial.locate(self.star_solver.empty_result(), self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        if not self.servo.flip_camera("UP"):
            return self.celestial.locate(self.star_solver.empty_result(), self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        assessment = self.sky_assessor.assess(cam0_up_frame)
        self._last_celestial_attempt = now
        if not assessment.usable_for_stars:
            self.servo.flip_camera("DOWN")
            return self.celestial.locate(self.star_solver.empty_result(), self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        star_solution = self.star_solver.solve(cam0_up_frame)
        result = self.celestial.locate(star_solution, self.imu.get_attitude(), self.context.pose.lat, self.context.pose.lon)
        self.servo.flip_camera("DOWN")
        return result


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
