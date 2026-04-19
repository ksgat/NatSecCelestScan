from __future__ import annotations

from math import cos, radians, tan

from ..config import CameraConfig, StereoConfig
from ..models import Attitude, StereoDepthResult

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class StereoDepthEstimator:
    def __init__(
        self,
        camera_config: CameraConfig | None = None,
        stereo_config: StereoConfig | None = None,
    ) -> None:
        self._camera_config = camera_config or CameraConfig()
        self._config = stereo_config or StereoConfig()
        self._clahe = None if cv2 is None else cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def update(self, left_frame, right_frame, attitude: Attitude | None = None) -> StereoDepthResult:
        if (
            left_frame is None
            or right_frame is None
            or np is None
            or cv2 is None
        ):
            return self._invalid()

        left_gray = self._prepare_gray(left_frame)
        right_gray = self._prepare_gray(right_frame)
        focal_length_px = left_gray.shape[1] / max(
            1e-6,
            2.0 * tan(radians(self._camera_config.down_fov_deg) * 0.5),
        )

        left_points = cv2.goodFeaturesToTrack(
            left_gray,
            maxCorners=self._config.orb_feature_count,
            qualityLevel=0.01,
            minDistance=7.0,
            blockSize=7,
        )
        if left_points is None or len(left_points) < self._config.min_match_count:
            return self._invalid()
        right_points, status, _ = cv2.calcOpticalFlowPyrLK(
            left_gray,
            right_gray,
            left_points,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if right_points is None or status is None:
            return self._invalid()
        back_points, back_status, _ = cv2.calcOpticalFlowPyrLK(
            right_gray,
            left_gray,
            right_points,
            None,
            winSize=(21, 21),
            maxLevel=3,
            criteria=(cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 30, 0.01),
        )
        if back_points is None or back_status is None:
            return self._invalid()

        left_points = left_points.reshape(-1, 2)
        right_points = right_points.reshape(-1, 2)
        back_points = back_points.reshape(-1, 2)
        status_mask = (status.reshape(-1) > 0) & (back_status.reshape(-1) > 0)
        fb_error = np.linalg.norm(left_points - back_points, axis=1)
        status_mask &= fb_error <= 1.5

        disparities: list[float] = []
        center_disparities: list[float] = []
        vertical_offsets: list[float] = []
        weights: list[float] = []
        center_weights: list[float] = []
        height, width = left_gray.shape[:2]
        half_window_x = width * self._config.center_window_fraction * 0.5
        half_window_y = height * self._config.center_window_fraction * 0.5
        center_x = width * 0.5
        center_y = height * 0.5

        for index, (left_point, right_point) in enumerate(zip(left_points, right_points)):
            if not status_mask[index]:
                continue
            x_left, y_left = left_point
            x_right, y_right = right_point
            disparity = abs(float(x_left - x_right))
            vertical_offset = abs(float(y_left - y_right))
            if disparity < self._config.min_disparity_px or disparity > self._config.max_disparity_px:
                continue
            if vertical_offset > self._config.vertical_tolerance_px:
                continue

            midpoint_x = (x_left + x_right) * 0.5
            midpoint_y = (y_left + y_right) * 0.5
            center_distance = ((midpoint_x - center_x) ** 2 + (midpoint_y - center_y) ** 2) ** 0.5
            center_weight = 1.0 / (1.0 + center_distance / max(1.0, min(width, height) * 0.25))
            match_weight = center_weight * (1.0 / (1.0 + fb_error[index]))

            disparities.append(disparity)
            vertical_offsets.append(vertical_offset)
            weights.append(match_weight)
            if abs(midpoint_x - center_x) <= half_window_x and abs(midpoint_y - center_y) <= half_window_y:
                center_disparities.append(disparity)
                center_weights.append(match_weight)

        if len(disparities) < self._config.min_match_count:
            return self._invalid()

        disparity_confidence = self._compute_confidence(
            disparities=disparities,
            center_disparities=center_disparities,
            vertical_offsets=vertical_offsets,
            image_width=width,
        )

        active_disparities = center_disparities if len(center_disparities) >= max(8, self._config.min_match_count // 2) else disparities
        active_weights = center_weights if len(center_weights) >= max(8, self._config.min_match_count // 2) else weights
        center_disparity_px = self._weighted_median(active_disparities, active_weights)
        if center_disparity_px <= 1e-6:
            return self._invalid()

        depths_m = [
            (focal_length_px * self._config.baseline_m) / max(1e-6, disparity)
            for disparity in active_disparities
        ]
        center_depth_m = self._weighted_median(depths_m, active_weights)
        altitude_m = center_depth_m * self._altitude_projection_factor(attitude)
        depth_variance = self._weighted_variance(depths_m, active_weights, center_depth_m)

        valid = (
            disparity_confidence >= 0.35
            and 0.5 <= center_depth_m <= 500.0
            and altitude_m > 0.2
        )
        return StereoDepthResult(
            valid=valid,
            altitude_m=altitude_m,
            disparity_confidence=disparity_confidence,
            center_depth_m=center_depth_m,
            depth_variance=depth_variance,
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

    def _compute_confidence(
        self,
        *,
        disparities: list[float],
        center_disparities: list[float],
        vertical_offsets: list[float],
        image_width: int,
    ) -> float:
        disparity_array = np.asarray(disparities, dtype=float)
        vertical_array = np.asarray(vertical_offsets, dtype=float)
        disparity_spread = float(np.std(disparity_array))
        vertical_mean = float(np.mean(vertical_array))
        center_ratio = len(center_disparities) / max(1, len(disparities))
        count_term = min(1.0, len(disparities) / max(1.0, self._config.min_match_count * 2.0))
        spread_term = max(0.0, min(1.0, 1.0 - disparity_spread / max(4.0, image_width * 0.05)))
        vertical_term = max(0.0, min(1.0, 1.0 - vertical_mean / max(1.0, self._config.vertical_tolerance_px)))
        center_term = max(0.0, min(1.0, center_ratio))
        return max(
            0.0,
            min(
                1.0,
                0.35 * count_term + 0.25 * spread_term + 0.25 * vertical_term + 0.15 * center_term,
            ),
        )

    @staticmethod
    def _weighted_median(values: list[float], weights: list[float]) -> float:
        if not values:
            return 0.0
        pairs = sorted(zip(values, weights), key=lambda item: item[0])
        total_weight = sum(max(0.0, weight) for _, weight in pairs)
        if total_weight <= 1e-9:
            return float(pairs[len(pairs) // 2][0])
        cumulative = 0.0
        midpoint = total_weight * 0.5
        for value, weight in pairs:
            cumulative += max(0.0, weight)
            if cumulative >= midpoint:
                return float(value)
        return float(pairs[-1][0])

    @staticmethod
    def _weighted_variance(values: list[float], weights: list[float], mean_value: float) -> float:
        if not values:
            return 999.0
        total_weight = sum(max(0.0, weight) for weight in weights)
        if total_weight <= 1e-9:
            diffs = [(value - mean_value) ** 2 for value in values]
            return float(sum(diffs) / max(1, len(diffs)))
        weighted_sum = 0.0
        for value, weight in zip(values, weights):
            weighted_sum += max(0.0, weight) * ((value - mean_value) ** 2)
        return float(weighted_sum / total_weight)

    @staticmethod
    def _altitude_projection_factor(attitude: Attitude | None) -> float:
        if attitude is None:
            return 1.0
        roll_factor = cos(radians(attitude.roll))
        pitch_factor = cos(radians(attitude.pitch))
        return max(0.15, abs(roll_factor * pitch_factor))

    @staticmethod
    def _invalid() -> StereoDepthResult:
        return StereoDepthResult(False, 0.0, 0.0, 0.0, 999.0)
