from __future__ import annotations

from .config import NavConfig
from .models import SkyAssessment

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None


class SkyAssessor:
    def __init__(self, config: NavConfig) -> None:
        self._config = config

    def assess(self, frame) -> SkyAssessment:
        if frame is None or np is None:
            return SkyAssessment(False, False, 0.0, 0.0, 0.0, 0, 1.0, 0.0)

        arr = np.asarray(frame)
        brightness = float(arr.mean() / 255.0)
        saturation_fraction = float((arr >= 250).mean())
        star_candidate_count = int((arr > 220).sum() // 20)
        sky_fraction = min(1.0, max(0.0, 0.6 + (0.5 - saturation_fraction) * 0.4))
        usable_for_stars = brightness < 0.25 and star_candidate_count >= self._config.sky_min_star_candidates
        usable_for_sun = brightness > 0.7 and saturation_fraction > 0.01
        occlusion_score = max(0.0, 1.0 - sky_fraction)
        confidence = max(0.0, min(1.0, sky_fraction * (1.0 - occlusion_score * 0.5)))
        return SkyAssessment(
            usable_for_sun=usable_for_sun,
            usable_for_stars=usable_for_stars,
            sky_fraction=sky_fraction,
            brightness=brightness,
            saturation_fraction=saturation_fraction,
            star_candidate_count=star_candidate_count,
            occlusion_score=occlusion_score,
            confidence=confidence,
        )

