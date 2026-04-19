from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise SystemExit("opencv-python is required for geo_match_debug.py") from exc


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pnt.config import NavConfig
from pnt.embedding_backend import build_embedding_backend
from pnt.geo_match import GeoMatcher
from pnt.map_manager import MapManager
from pnt.models import Attitude


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one image through the geo-match retrieval pipeline.")
    parser.add_argument("image", help="Path to a downward-looking test image")
    parser.add_argument("--collection-id", default="", help="Dashboard collection id to use")
    parser.add_argument("--lat", type=float, default=None, help="Seed latitude")
    parser.add_argument("--lon", type=float, default=None, help="Seed longitude")
    parser.add_argument("--altitude-m", type=float, default=60.0, help="Altitude prior in meters")
    parser.add_argument("--yaw-deg", type=float, default=0.0, help="Heading prior in degrees")
    parser.add_argument("--device", default="", help="Override embedding backend device, e.g. cpu or cuda")
    parser.add_argument("--model-name", default="", help="Override embedding backend model name")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    image_path = Path(args.image)
    if not image_path.is_absolute():
        image_path = (REPO_ROOT / image_path).resolve()
    if not image_path.exists():
        raise SystemExit(f"image not found: {image_path}")

    frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if frame is None:
        raise SystemExit(f"failed to load image: {image_path}")

    config = NavConfig()
    if args.collection_id:
        config.maps.active_collection_id = args.collection_id
    if args.device:
        config.maps.embedding_device = args.device
    if args.model_name:
        config.maps.embedding_model_name = args.model_name

    seed_lat = args.lat
    seed_lon = args.lon
    if seed_lat is None:
        seed_lat = (config.mission_bounds.min_lat + config.mission_bounds.max_lat) / 2.0
    if seed_lon is None:
        seed_lon = (config.mission_bounds.min_lon + config.mission_bounds.max_lon) / 2.0

    backend = build_embedding_backend(config.maps.embedding_model_name, config.maps.embedding_device)
    maps = MapManager(config.root_dir, config.mission_bounds, config.maps)
    matcher = GeoMatcher(maps, backend, config.maps)
    result = matcher.update(
        frame=frame,
        altitude_m=args.altitude_m,
        attitude=Attitude(yaw=args.yaw_deg),
        seed_lat=seed_lat,
        seed_lon=seed_lon,
    )

    payload = {
        "image": str(image_path),
        "seed_lat": seed_lat,
        "seed_lon": seed_lon,
        "altitude_m": args.altitude_m,
        "yaw_deg": args.yaw_deg,
        "active_collection_id": maps.active_collection_id,
        "backend": backend.status().__dict__,
        "result": {
            "valid": result.valid,
            "lat": result.lat,
            "lon": result.lon,
            "heading_deg": result.heading_deg,
            "match_score": result.match_score,
            "inlier_count": result.inlier_count,
            "scale_error": result.scale_error,
            "confidence": result.confidence,
            "source": result.source,
            "candidate_count": result.candidate_count,
            "verified": result.verified,
            "structural_score": result.structural_score,
            "tile_path": result.tile_path,
        },
    }

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"image={payload['image']}")
    print(f"seed=({seed_lat:.6f}, {seed_lon:.6f}) altitude_m={args.altitude_m:.1f} yaw_deg={args.yaw_deg:.1f}")
    print(f"collection={payload['active_collection_id'] or 'none'}")
    print(
        "backend="
        f"{payload['backend']['model_name']} "
        f"device={payload['backend']['device']} "
        f"available={payload['backend']['available']}"
    )
    if payload["backend"]["last_error"]:
        print(f"backend_error={payload['backend']['last_error']}")
    print(
        "result="
        f"valid={result.valid} "
        f"verified={result.verified} "
        f"candidates={result.candidate_count} "
        f"score={result.match_score:.3f} "
        f"confidence={result.confidence:.3f} "
        f"structural={result.structural_score:.3f}"
    )
    print(
        "fix="
        f"lat={result.lat:.6f} "
        f"lon={result.lon:.6f} "
        f"inliers={result.inlier_count} "
        f"scale_error={result.scale_error:.3f}"
    )
    if result.tile_path:
        print(f"tile={result.tile_path}")


if __name__ == "__main__":
    main()
