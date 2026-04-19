from __future__ import annotations

from dataclasses import dataclass
from math import tan, radians

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from .config import MapCollectionConfig
from .embedding_backend import EmbeddingBackend
from .map_manager import MapManager
from .models import Attitude, GeoMatchResult, MapTileCandidate


@dataclass
class VerificationResult:
    valid: bool
    lat: float
    lon: float
    inlier_count: int
    inlier_ratio: float
    reprojection_error: float
    structural_score: float


@dataclass
class PreparedImage:
    gray: object
    feature: object
    edges: object
    corner_map: object
    corner_count: int


class GeoMatcher:
    def __init__(self, map_manager: MapManager, embedding_backend: EmbeddingBackend, config: MapCollectionConfig) -> None:
        self._map_manager = map_manager
        self._embedding_backend = embedding_backend
        self._config = config
        self._orb = None if cv2 is None else cv2.ORB_create(nfeatures=self._config.orb_feature_count)
        self._matcher = None if cv2 is None else cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        self._clahe = None if cv2 is None else cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    def update(self, frame, altitude_m: float, attitude: Attitude, seed_lat: float, seed_lon: float) -> GeoMatchResult:
        if frame is None or np is None or cv2 is None or self._orb is None or self._matcher is None:
            return self._invalid(seed_lat, seed_lon, attitude.yaw)

        query_embedding = None
        if self._config.use_runtime_embeddings and self._map_manager.has_embeddings():
            query_embedding = self._embedding_backend.embed_frame(frame)

        candidates = self._map_manager.query_candidate_tiles(
            seed_lat,
            seed_lon,
            query_embedding=query_embedding,
            top_k=self._config.candidate_search_limit,
        )
        if not candidates:
            return self._invalid(seed_lat, seed_lon, attitude.yaw)

        live = self._prepare_live_image(frame)
        kp_live, des_live = self._orb.detectAndCompute(live.feature, None)
        if des_live is None or len(kp_live) < max(12, self._config.verify_min_inliers):
            return self._invalid(seed_lat, seed_lon, attitude.yaw)

        best_result: GeoMatchResult | None = None
        for candidate in candidates:
            verification = self._verify_candidate(
                live=live,
                kp_live=kp_live,
                des_live=des_live,
                candidate=candidate,
                altitude_m=altitude_m,
            )
            scale_error = self._estimate_scale_error(candidate, altitude_m, live.gray.shape[1])
            confidence = self._combine_confidence(candidate, verification, scale_error)
            valid = (
                verification.valid
                and verification.structural_score >= self._config.verify_min_structural_score
                and confidence >= 0.55
            )
            result = GeoMatchResult(
                valid=valid,
                lat=verification.lat if verification.valid else candidate.lat_center,
                lon=verification.lon if verification.valid else candidate.lon_center,
                heading_deg=attitude.yaw,
                match_score=max(candidate.embedding_score, verification.inlier_ratio, verification.structural_score),
                inlier_count=verification.inlier_count,
                scale_error=scale_error,
                confidence=confidence,
                source=candidate.source,
                candidate_count=len(candidates),
                verified=verification.valid,
                structural_score=verification.structural_score,
                tile_path=str(candidate.path),
            )
            if best_result is None or self._is_better(result, best_result):
                best_result = result

        return best_result if best_result is not None else self._invalid(seed_lat, seed_lon, attitude.yaw)

    def _verify_candidate(self, live: PreparedImage, kp_live, des_live, candidate: MapTileCandidate, altitude_m: float) -> VerificationResult:
        if not candidate.path.exists():
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, 0, 0.0, 999.0, 0.0)

        tile_image = cv2.imread(str(candidate.path), cv2.IMREAD_COLOR)
        if tile_image is None:
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, 0, 0.0, 999.0, 0.0)

        tile = self._prepare_tile_image(tile_image, candidate, altitude_m, live.gray.shape[1])
        kp_tile, des_tile = self._orb.detectAndCompute(tile.feature, None)
        if des_tile is None or len(kp_tile) < max(12, self._config.verify_min_inliers):
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, 0, 0.0, 999.0, 0.0)

        knn_matches = self._matcher.knnMatch(des_live, des_tile, k=2)
        good_matches = []
        for pair in knn_matches:
            if len(pair) < 2:
                continue
            first, second = pair
            if first.distance < self._config.match_ratio_test * second.distance:
                good_matches.append(first)
        if len(good_matches) < max(8, self._config.verify_min_inliers):
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, 0, 0.0, 999.0, 0.0)

        src_pts = np.float32([kp_live[m.queryIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        dst_pts = np.float32([kp_tile[m.trainIdx].pt for m in good_matches]).reshape(-1, 1, 2)
        homography, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, self._config.ransac_reproj_threshold_px)
        if homography is None or mask is None:
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, 0, 0.0, 999.0, 0.0)

        inlier_mask = mask.ravel().astype(bool)
        inlier_count = int(inlier_mask.sum())
        inlier_ratio = inlier_count / max(1, len(good_matches))
        if inlier_count < self._config.verify_min_inliers or inlier_ratio < self._config.verify_min_inlier_ratio:
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, inlier_count, inlier_ratio, 999.0, 0.0)

        reprojection_error = self._compute_reprojection_error(src_pts[inlier_mask], dst_pts[inlier_mask], homography)
        structural_score = self._compute_structural_score(live, tile, homography)
        height, width = live.gray.shape[:2]
        center = np.array([[[width * 0.5, height * 0.5]]], dtype=np.float32)
        projected = cv2.perspectiveTransform(center, homography)
        px = float(projected[0, 0, 0])
        py = float(projected[0, 0, 1])
        tile_h, tile_w = tile.gray.shape[:2]
        if px < -0.1 * tile_w or px > 1.1 * tile_w or py < -0.1 * tile_h or py > 1.1 * tile_h:
            return VerificationResult(False, candidate.lat_center, candidate.lon_center, inlier_count, inlier_ratio, reprojection_error, structural_score)

        px = min(max(px, 0.0), max(1.0, tile_w - 1.0))
        py = min(max(py, 0.0), max(1.0, tile_h - 1.0))
        lon = candidate.west + (px / tile_w) * (candidate.east - candidate.west)
        lat = candidate.north - (py / tile_h) * (candidate.north - candidate.south)
        return VerificationResult(True, lat, lon, inlier_count, inlier_ratio, reprojection_error, structural_score)

    def _prepare_live_image(self, frame):
        gray = self._to_gray(frame)
        return self._prepare_image(gray)

    def _prepare_tile_image(self, tile_image, candidate: MapTileCandidate, altitude_m: float, live_width_px: int):
        gray = self._to_gray(tile_image)
        scale = self._expected_tile_scale(candidate, altitude_m, live_width_px)
        if abs(scale - 1.0) > 0.15:
            new_w = int(max(64, min(2048, round(gray.shape[1] * scale))))
            new_h = int(max(64, min(2048, round(gray.shape[0] * scale))))
            gray = cv2.resize(gray, (new_w, new_h), interpolation=cv2.INTER_LINEAR)
        return self._prepare_image(gray)

    def _prepare_image(self, gray) -> PreparedImage:
        gray = self._clahe.apply(gray)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(
            blurred,
            self._config.canny_low_threshold,
            self._config.canny_high_threshold,
        )
        feature = cv2.addWeighted(
            gray,
            max(0.0, min(1.0, 1.0 - self._config.edge_weight)),
            edges,
            max(0.0, min(1.0, self._config.edge_weight)),
            0.0,
        )
        corner_map, corner_count = self._build_corner_map(gray)
        return PreparedImage(
            gray=gray,
            feature=feature,
            edges=edges,
            corner_map=corner_map,
            corner_count=corner_count,
        )

    def _build_corner_map(self, gray) -> tuple[object, int]:
        corner_map = np.zeros_like(gray, dtype=np.uint8)
        corners = cv2.goodFeaturesToTrack(
            gray,
            maxCorners=self._config.corner_max_count,
            qualityLevel=self._config.corner_quality_level,
            minDistance=self._config.corner_min_distance_px,
            blockSize=7,
            useHarrisDetector=False,
        )
        if corners is None:
            return corner_map, 0
        for corner in corners.reshape(-1, 2):
            x = int(round(float(corner[0])))
            y = int(round(float(corner[1])))
            if 0 <= x < corner_map.shape[1] and 0 <= y < corner_map.shape[0]:
                corner_map[y, x] = 255
        corner_map = cv2.dilate(corner_map, np.ones((5, 5), dtype=np.uint8), iterations=1)
        return corner_map, int(len(corners))

    def _expected_tile_scale(self, candidate: MapTileCandidate, altitude_m: float, live_width_px: int) -> float:
        if altitude_m <= 0.0 or live_width_px <= 0:
            return 1.0
        live_ground_width_m = 2.0 * altitude_m * tan(radians(self._config.down_camera_fov_deg) * 0.5)
        if live_ground_width_m <= 1e-6:
            return 1.0
        live_mpp = live_ground_width_m / live_width_px
        if live_mpp <= 1e-6:
            return 1.0
        scale = candidate.meters_per_pixel / live_mpp
        return min(4.0, max(0.5, scale))

    @staticmethod
    def _compute_reprojection_error(src_pts, dst_pts, homography) -> float:
        if len(src_pts) == 0:
            return 999.0
        projected = cv2.perspectiveTransform(src_pts, homography)
        errors = np.linalg.norm(projected.reshape(-1, 2) - dst_pts.reshape(-1, 2), axis=1)
        return float(errors.mean()) if len(errors) else 999.0

    def _compute_structural_score(self, live: PreparedImage, tile: PreparedImage, homography) -> float:
        tile_h, tile_w = tile.gray.shape[:2]
        warp_shape = (tile_w, tile_h)
        live_mask = np.full(live.gray.shape[:2], 255, dtype=np.uint8)
        warped_mask = cv2.warpPerspective(live_mask, homography, warp_shape)
        warped_edges = cv2.warpPerspective(live.edges, homography, warp_shape)
        warped_corners = cv2.warpPerspective(live.corner_map, homography, warp_shape)

        edge_score = self._masked_binary_dice(warped_edges, tile.edges, warped_mask)
        corner_score = self._masked_binary_dice(warped_corners, tile.corner_map, warped_mask)
        density_score = self._density_consistency_score(live, tile, warped_mask)
        return max(
            0.0,
            min(
                1.0,
                0.50 * edge_score + 0.30 * corner_score + 0.20 * density_score,
            ),
        )

    @staticmethod
    def _masked_binary_dice(first, second, mask) -> float:
        mask_bool = mask > 0
        if not np.any(mask_bool):
            return 0.0
        first_bool = (first > 0) & mask_bool
        second_bool = (second > 0) & mask_bool
        first_count = int(first_bool.sum())
        second_count = int(second_bool.sum())
        if first_count == 0 and second_count == 0:
            return 1.0
        if first_count == 0 or second_count == 0:
            return 0.0
        intersection = int((first_bool & second_bool).sum())
        return (2.0 * intersection) / max(1.0, first_count + second_count)

    @staticmethod
    def _density_consistency_score(live: PreparedImage, tile: PreparedImage, warped_mask) -> float:
        mask_bool = warped_mask > 0
        if not np.any(mask_bool):
            return 0.0
        live_edge_density = float((live.edges > 0).mean())
        tile_edge_density = float((tile.edges[mask_bool] > 0).mean())
        live_corner_density = float((live.corner_map > 0).mean())
        tile_corner_density = float((tile.corner_map[mask_bool] > 0).mean())
        edge_delta = abs(live_edge_density - tile_edge_density)
        corner_delta = abs(live_corner_density - tile_corner_density)
        return max(0.0, min(1.0, 1.0 - 2.0 * edge_delta - 3.0 * corner_delta))

    @staticmethod
    def _to_gray(frame):
        array = np.asarray(frame)
        if array.ndim == 2:
            return array
        if array.shape[2] == 4:
            array = array[..., :3]
        return cv2.cvtColor(array, cv2.COLOR_BGR2GRAY)

    def _estimate_scale_error(self, candidate: MapTileCandidate, altitude_m: float, live_width_px: int) -> float:
        if altitude_m <= 0.0:
            return 1.0
        live_ground_width_m = 2.0 * altitude_m * tan(radians(self._config.down_camera_fov_deg) * 0.5)
        if live_ground_width_m <= 1e-6 or live_width_px <= 0:
            return 1.0
        expected_live_mpp = live_ground_width_m / live_width_px
        if expected_live_mpp <= 1e-6:
            return 1.0
        return min(1.0, abs(candidate.meters_per_pixel - expected_live_mpp) / expected_live_mpp)

    @staticmethod
    def _combine_confidence(candidate: MapTileCandidate, verification: VerificationResult, scale_error: float) -> float:
        inlier_term = max(0.0, min(1.0, verification.inlier_count / 48.0))
        ratio_term = max(0.0, min(1.0, verification.inlier_ratio))
        reprojection_term = max(0.0, min(1.0, 1.0 - verification.reprojection_error / 10.0))
        structure_term = max(0.0, min(1.0, verification.structural_score))
        distance_term = max(0.0, min(1.0, 1.0 - candidate.distance_m / 2500.0))
        scale_term = 1.0 - max(0.0, min(1.0, scale_error))
        embedding_term = max(0.0, min(1.0, candidate.embedding_score))
        return max(
            0.0,
            min(
                1.0,
                0.24 * inlier_term
                + 0.20 * ratio_term
                + 0.15 * reprojection_term
                + 0.18 * structure_term
                + 0.12 * distance_term
                + 0.06 * scale_term
                + 0.05 * embedding_term,
            ),
        )

    @staticmethod
    def _is_better(current: GeoMatchResult, previous: GeoMatchResult) -> bool:
        if current.valid != previous.valid:
            return current.valid
        if current.verified != previous.verified:
            return current.verified
        if abs(current.confidence - previous.confidence) > 1e-6:
            return current.confidence > previous.confidence
        return current.inlier_count > previous.inlier_count

    @staticmethod
    def _invalid(lat: float, lon: float, heading: float) -> GeoMatchResult:
        return GeoMatchResult(False, lat, lon, heading, 0.0, 0, 1.0, 0.0, "cached")
