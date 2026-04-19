from __future__ import annotations

from math import cos, radians, sin, sqrt, tan

from .config import CameraConfig, VisualOdometryConfig
from .models import Attitude, VisualOdometryResult

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class VisualOdometry:
    def __init__(
        self,
        camera_config: CameraConfig | None = None,
        vo_config: VisualOdometryConfig | None = None,
    ) -> None:
        self._camera_config = camera_config or CameraConfig()
        self._config = vo_config or VisualOdometryConfig()
        self._clahe = None if cv2 is None else cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
        self._prev_gray = None
        self._prev_timestamp: float | None = None
        self._prev_attitude: Attitude | None = None
        self._last_altitude_m: float | None = None

    def update(self, frame, attitude: Attitude, altitude_m: float, timestamp: float) -> VisualOdometryResult:
        if frame is None or np is None or cv2 is None:
            return self._invalid()

        gray = self._prepare_gray(frame)
        effective_altitude_m = self._resolve_altitude(altitude_m)
        if self._prev_gray is None or self._prev_timestamp is None or self._prev_attitude is None:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        dt_s = max(1e-3, timestamp - self._prev_timestamp)
        previous_points = cv2.goodFeaturesToTrack(
            self._prev_gray,
            maxCorners=self._config.max_corners,
            qualityLevel=self._config.quality_level,
            minDistance=self._config.min_distance_px,
            blockSize=7,
        )
        if previous_points is None or len(previous_points) < self._config.min_track_count:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        current_points, status, _ = cv2.calcOpticalFlowPyrLK(
            self._prev_gray,
            gray,
            previous_points,
            None,
            winSize=(self._config.lk_win_size_px, self._config.lk_win_size_px),
            maxLevel=self._config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if current_points is None or status is None:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        back_points, back_status, _ = cv2.calcOpticalFlowPyrLK(
            gray,
            self._prev_gray,
            current_points,
            None,
            winSize=(self._config.lk_win_size_px, self._config.lk_win_size_px),
            maxLevel=self._config.lk_max_level,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if back_points is None or back_status is None:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        prev_pts = previous_points.reshape(-1, 2)
        curr_pts = current_points.reshape(-1, 2)
        back_pts = back_points.reshape(-1, 2)
        status_mask = (status.reshape(-1) > 0) & (back_status.reshape(-1) > 0)
        fb_error = np.linalg.norm(prev_pts - back_pts, axis=1)
        status_mask &= fb_error <= self._config.fb_max_error_px
        prev_good = prev_pts[status_mask]
        curr_good = curr_pts[status_mask]

        if len(prev_good) < self._config.min_track_count:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        affine, inlier_mask = cv2.estimateAffinePartial2D(
            prev_good,
            curr_good,
            method=cv2.RANSAC,
            ransacReprojThreshold=self._config.ransac_reproj_threshold_px,
            maxIters=2000,
            confidence=0.995,
        )
        if affine is None or inlier_mask is None:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        inlier_mask = inlier_mask.reshape(-1).astype(bool)
        prev_inliers = prev_good[inlier_mask]
        curr_inliers = curr_good[inlier_mask]
        inlier_count = int(len(prev_inliers))
        if inlier_count < self._config.min_track_count:
            self._store_state(gray, attitude, timestamp, effective_altitude_m)
            return self._invalid()

        track_count = int(len(prev_good))
        inlier_ratio = inlier_count / max(1, track_count)
        dx_px = float(affine[0, 2])
        dy_px = float(affine[1, 2])
        visual_rotation_deg = float(np.degrees(np.arctan2(affine[1, 0], affine[0, 0])))
        imu_delta_yaw_deg = self._angle_delta_deg(attitude.yaw, self._prev_attitude.yaw)
        rotation_mismatch_deg = abs(self._angle_delta_deg(visual_rotation_deg, imu_delta_yaw_deg))
        tilt_change_deg = sqrt(
            (attitude.roll - self._prev_attitude.roll) ** 2 + (attitude.pitch - self._prev_attitude.pitch) ** 2
        )
        parallax_score = float(np.median(np.linalg.norm(curr_inliers - prev_inliers, axis=1)))
        reprojection_error = self._compute_affine_error(prev_inliers, curr_inliers, affine)
        feature_quality = min(1.0, track_count / max(1.0, self._config.max_corners * 0.7))

        meters_per_pixel = self._meters_per_pixel(effective_altitude_m, attitude, gray.shape[1])
        camera_forward_m = -dy_px * meters_per_pixel
        camera_right_m = -dx_px * meters_per_pixel
        body_forward_m, body_right_m = self._camera_to_body(camera_forward_m, camera_right_m)
        average_yaw_deg = self._prev_attitude.yaw + (imu_delta_yaw_deg * 0.5)
        delta_east_m, delta_north_m = self._body_to_enu(body_forward_m, body_right_m, average_yaw_deg)
        step_m = sqrt(delta_east_m * delta_east_m + delta_north_m * delta_north_m)
        velocity = (
            delta_east_m / dt_s,
            delta_north_m / dt_s,
            0.0,
        )

        rotation_term = max(
            0.0,
            min(1.0, 1.0 - rotation_mismatch_deg / max(1e-6, self._config.max_rotation_mismatch_deg)),
        )
        tilt_term = max(0.0, min(1.0, 1.0 - tilt_change_deg / max(1e-6, self._config.max_tilt_change_deg)))
        reprojection_term = max(0.0, min(1.0, 1.0 - reprojection_error / 10.0))
        parallax_term = max(0.0, min(1.0, parallax_score / 12.0))
        altitude_term = 1.0 if effective_altitude_m is not None and effective_altitude_m > 0.25 else 0.0
        confidence = max(
            0.0,
            min(
                1.0,
                0.20 * feature_quality
                + 0.20 * inlier_ratio
                + 0.15 * parallax_term
                + 0.15 * reprojection_term
                + 0.20 * rotation_term
                + 0.05 * tilt_term
                + 0.05 * altitude_term,
            ),
        )
        valid = (
            effective_altitude_m is not None
            and inlier_count >= self._config.min_track_count
            and inlier_ratio >= 0.35
            and confidence >= 0.45
            and step_m <= self._config.max_step_m_per_frame
        )

        self._store_state(gray, attitude, timestamp, effective_altitude_m)
        return VisualOdometryResult(
            valid=valid,
            delta_position_m=(delta_east_m, delta_north_m, 0.0),
            delta_yaw_deg=imu_delta_yaw_deg,
            velocity_mps=velocity,
            track_count=track_count,
            inlier_ratio=inlier_ratio,
            parallax_score=parallax_score,
            reprojection_error=reprojection_error,
            feature_quality=feature_quality,
            confidence=confidence,
        )

    def _prepare_gray(self, frame):
        array = np.asarray(frame)
        if array.ndim == 2:
            gray = array
        else:
            if array.shape[2] == 4:
                array = array[..., :3]
            gray = cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)
        if self._clahe is not None:
            gray = self._clahe.apply(gray)
        return cv2.GaussianBlur(gray, (5, 5), 0)

    def _resolve_altitude(self, altitude_m: float) -> float | None:
        if altitude_m > 0.25:
            self._last_altitude_m = altitude_m
            return altitude_m
        return self._last_altitude_m

    def _meters_per_pixel(self, altitude_m: float | None, attitude: Attitude, frame_width_px: int) -> float:
        if altitude_m is None:
            return 0.0
        projection_factor = max(
            0.15,
            abs(cos(radians(attitude.roll)) * cos(radians(attitude.pitch))),
        )
        effective_altitude_m = altitude_m * projection_factor
        ground_width_m = 2.0 * effective_altitude_m * tan(radians(self._camera_config.down_fov_deg) * 0.5)
        return ground_width_m / max(1.0, float(frame_width_px))

    def _camera_to_body(self, camera_forward_m: float, camera_right_m: float) -> tuple[float, float]:
        offset_rad = radians(self._camera_config.down_camera_yaw_offset_deg)
        body_forward_m = camera_forward_m * cos(offset_rad) - camera_right_m * sin(offset_rad)
        body_right_m = camera_forward_m * sin(offset_rad) + camera_right_m * cos(offset_rad)
        return body_forward_m, body_right_m

    @staticmethod
    def _body_to_enu(forward_m: float, right_m: float, yaw_deg: float) -> tuple[float, float]:
        yaw_rad = radians(yaw_deg)
        east_m = right_m * cos(yaw_rad) + forward_m * sin(yaw_rad)
        north_m = forward_m * cos(yaw_rad) - right_m * sin(yaw_rad)
        return east_m, north_m

    @staticmethod
    def _compute_affine_error(prev_pts, curr_pts, affine) -> float:
        if len(prev_pts) == 0:
            return 999.0
        prev_h = np.hstack([prev_pts, np.ones((len(prev_pts), 1), dtype=np.float32)])
        predicted = (affine @ prev_h.T).T
        errors = np.linalg.norm(predicted - curr_pts, axis=1)
        return float(errors.mean()) if len(errors) else 999.0

    @staticmethod
    def _angle_delta_deg(current_deg: float, previous_deg: float) -> float:
        delta = current_deg - previous_deg
        while delta > 180.0:
            delta -= 360.0
        while delta < -180.0:
            delta += 360.0
        return delta

    def _store_state(self, gray, attitude: Attitude, timestamp: float, altitude_m: float | None) -> None:
        self._prev_gray = gray
        self._prev_timestamp = timestamp
        self._prev_attitude = Attitude(attitude.roll, attitude.pitch, attitude.yaw)
        if altitude_m is not None:
            self._last_altitude_m = altitude_m

    @staticmethod
    def _invalid() -> VisualOdometryResult:
        return VisualOdometryResult(
            valid=False,
            delta_position_m=(0.0, 0.0, 0.0),
            delta_yaw_deg=0.0,
            velocity_mps=(0.0, 0.0, 0.0),
            track_count=0,
            inlier_ratio=0.0,
            parallax_score=0.0,
            reprojection_error=999.0,
            feature_quality=0.0,
            confidence=0.0,
        )
