from __future__ import annotations

from ..models import StereoDepthResult

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class StereoDepthEstimator:
    def update(self, left_frame, right_frame) -> StereoDepthResult:
        if left_frame is None or right_frame is None or np is None:
            return StereoDepthResult(False, 0.0, 0.0, 0.0, 999.0)
        left = np.asarray(left_frame)
        right = np.asarray(right_frame)
        diff = abs(float(left.mean() - right.mean()))
        disparity_confidence = max(0.0, min(1.0, 1.0 - diff / 255.0))
        altitude_m = 20.0 + diff * 0.05
        return StereoDepthResult(disparity_confidence >= 0.2, altitude_m, disparity_confidence, altitude_m, 1.0 - disparity_confidence)

