from __future__ import annotations

from .models import Attitude, VisualOdometryResult

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class VisualOdometry:
    def __init__(self) -> None:
        self._prev_frame = None
        self._prev_timestamp = None

    def update(self, left_frame, right_frame, attitude: Attitude, timestamp: float) -> VisualOdometryResult:
        if left_frame is None or right_frame is None or np is None:
            return self._invalid()

        left = np.asarray(left_frame)
        right = np.asarray(right_frame)
        track_count = int(min(left.size, right.size) ** 0.5 // 4)
        contrast = float(left.std() / 64.0)
        feature_quality = max(0.0, min(1.0, contrast))
        inlier_ratio = max(0.0, min(1.0, feature_quality * 0.8))
        parallax_score = max(0.0, min(1.0, abs(float(left.mean() - right.mean())) / 32.0))
        reprojection_error = max(0.1, 3.0 - feature_quality * 2.5)
        confidence = max(0.0, min(1.0, 0.45 * feature_quality + 0.35 * inlier_ratio + 0.2 * parallax_score))
        valid = track_count >= 20 and confidence >= 0.35
        velocity = (0.0, 0.0, 0.0)
        if self._prev_timestamp is not None and timestamp > self._prev_timestamp:
            dt = timestamp - self._prev_timestamp
            velocity = (0.0, 0.0, 0.0 if dt <= 0 else 0.1 * feature_quality)
        self._prev_frame = left
        self._prev_timestamp = timestamp
        return VisualOdometryResult(
            valid=valid,
            delta_position_m=(0.0, 0.0, 0.0),
            delta_yaw_deg=0.0,
            velocity_mps=velocity,
            track_count=track_count,
            inlier_ratio=inlier_ratio,
            parallax_score=parallax_score,
            reprojection_error=reprojection_error,
            feature_quality=feature_quality,
            confidence=confidence,
        )

    @staticmethod
    def _invalid() -> VisualOdometryResult:
        return VisualOdometryResult(False, (0.0, 0.0, 0.0), 0.0, (0.0, 0.0, 0.0), 0, 0.0, 0.0, 999.0, 0.0, 0.0)

