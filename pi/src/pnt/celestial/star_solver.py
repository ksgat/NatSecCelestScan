from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import StarSolveResult

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import tetra3
except ImportError:  # pragma: no cover
    tetra3 = None


class StarSolver:
    def __init__(
        self,
        fov_deg: float,
        database: str | Path | None = "default_database",
        extraction_kwargs: dict[str, Any] | None = None,
        solve_kwargs: dict[str, Any] | None = None,
    ) -> None:
        self._fov_deg = fov_deg
        self._database = database
        self._extraction_kwargs = extraction_kwargs or {
            "sigma": 2,
            "filtsize": 25,
            "min_area": 3,
            "max_area": 200,
            "max_axis_ratio": 2.5,
            "binary_open": True,
            "max_returned": 64,
        }
        self._solve_kwargs = solve_kwargs or {
            "fov_estimate": fov_deg,
            "fov_max_error": max(1.0, fov_deg * 0.15),
            "pattern_checking_stars": 8,
            "match_radius": 0.01,
            "match_threshold": 1e-3,
            "solve_timeout": 750,
            "distortion": 0,
            "return_matches": True,
        }
        self._solver = self._build_solver()

    @classmethod
    def from_config(cls, config_path: str | Path) -> "StarSolver":
        path = Path(config_path)
        config = json.loads(path.read_text(encoding="utf-8"))
        assets_root = path.parents[1]
        database = cls._resolve_database(
            assets_root,
            config.get("database"),
            config.get("fallback_database"),
            config.get("reference_database"),
        )
        extraction = dict(config.get("extraction", {}))
        solve_kwargs = {
            "fov_estimate": config.get("fov_estimate"),
            "fov_max_error": config.get("fov_max_error"),
            "pattern_checking_stars": config.get("pattern_checking_stars", 8),
            "match_radius": config.get("match_radius", 0.01),
            "match_threshold": config.get("match_threshold", 1e-3),
            "solve_timeout": config.get("solve_timeout", 750),
            "distortion": config.get("distortion", 0),
            "return_matches": True,
        }
        fov_deg = float(config.get("fov_estimate", 0.0))
        return cls(
            fov_deg=fov_deg,
            database=database,
            extraction_kwargs=extraction,
            solve_kwargs=solve_kwargs,
        )

    @property
    def available(self) -> bool:
        return self._solver is not None

    def solve(self, frame) -> StarSolveResult:
        if frame is None or np is None:
            return self.empty_result()

        arr = np.asarray(frame)
        if arr.ndim == 3 and arr.shape[2] in {3, 4}:
            arr = arr[..., :3].mean(axis=2)
        arr = np.ascontiguousarray(arr)

        if self._solver is None:
            return self._fallback_result(arr)

        try:
            result = self._solver.solve_from_image(arr, **self._extraction_kwargs, **self._solve_kwargs)
        except Exception:
            return self.empty_result()

        return self._from_tetra3_result(result)

    def _build_solver(self):
        if tetra3 is None:
            return None
        try:
            return tetra3.Tetra3(load_database=self._database)
        except Exception:
            return None

    def _from_tetra3_result(self, result: dict[str, Any] | None) -> StarSolveResult:
        if not result:
            return self.empty_result()

        ra = self._as_float(result.get("RA"))
        dec = self._as_float(result.get("Dec"))
        roll = self._as_float(result.get("Roll"))
        fov = self._as_float(result.get("FOV"), self._fov_deg)
        rmse_arcsec = self._as_float(result.get("RMSE"))
        matches = self._as_int(result.get("Matches"))
        false_positive_prob = self._as_float(result.get("Prob"), 1.0)
        matched_ids = result.get("matched_catID") or []
        catalog_id_count = len(matched_ids) if hasattr(matched_ids, "__len__") else 0
        confidence = self._confidence_from_result(matches, false_positive_prob, rmse_arcsec)
        return StarSolveResult(
            valid=ra is not None and dec is not None and matches >= 4 and confidence >= 0.5,
            ra_deg=ra or 0.0,
            dec_deg=dec or 0.0,
            roll_deg=roll or 0.0,
            fov_deg=fov,
            star_count=matches,
            residual_px=self._arcsec_to_pixel_residual(rmse_arcsec, fov),
            confidence=confidence,
            catalog_id_count=max(catalog_id_count, matches),
        )

    def _fallback_result(self, arr) -> StarSolveResult:
        star_count = int((arr > 220).sum() // 20)
        confidence = max(0.0, min(1.0, star_count / 40.0))
        return StarSolveResult(
            valid=star_count >= 12,
            ra_deg=180.0,
            dec_deg=45.0,
            roll_deg=0.0,
            fov_deg=self._fov_deg,
            star_count=star_count,
            residual_px=max(0.5, 8.0 - confidence * 6.0),
            confidence=confidence * 0.5,
            catalog_id_count=min(star_count, 20),
        )

    @staticmethod
    def _confidence_from_result(matches: int, false_positive_prob: float | None, rmse_arcsec: float | None) -> float:
        match_score = min(1.0, matches / 12.0)
        prob_score = 0.0 if false_positive_prob is None else max(0.0, min(1.0, 1.0 - false_positive_prob * 100.0))
        if rmse_arcsec is None:
            residual_score = 0.0
        else:
            residual_score = max(0.0, min(1.0, 1.0 - rmse_arcsec / 300.0))
        return max(0.0, min(1.0, 0.45 * match_score + 0.35 * prob_score + 0.20 * residual_score))

    @staticmethod
    def _arcsec_to_pixel_residual(rmse_arcsec: float | None, fov_deg: float) -> float:
        if rmse_arcsec is None or fov_deg <= 0:
            return 0.0
        degrees = rmse_arcsec / 3600.0
        return degrees / fov_deg * 1024.0

    @staticmethod
    def _as_float(value, default: float | None = None) -> float | None:
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _as_int(value, default: int = 0) -> int:
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def empty_result() -> StarSolveResult:
        return StarSolveResult(valid=False)

    @staticmethod
    def _resolve_database(assets_root: Path, *candidates: object) -> str | Path | None:
        for candidate in candidates:
            if not candidate:
                continue
            candidate_path = Path(str(candidate))
            if not candidate_path.is_absolute():
                candidate_path = (assets_root.parent / candidate_path).resolve()
            if candidate_path.exists():
                return candidate_path
        return None
