from __future__ import annotations

import argparse
import json
import math
import random
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise SystemExit("opencv-python is required for generate_synth_data.py") from exc

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise SystemExit("numpy is required for generate_synth_data.py") from exc


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pnt.config import NavConfig
from pnt.map_manager import tile_bounds, tile_meters_per_pixel


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate synthetic geo-match test images from a cached tile collection.")
    parser.add_argument("--collection-id", default="", help="Tile collection id. Defaults to the latest collection.")
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "pi" / "src" / "assets" / "test_images" / "ground" / "synthetic"),
        help="Root directory where synthetic datasets should be written.",
    )
    parser.add_argument("--count-per-zoom", type=int, default=6, help="How many source tiles to sample per zoom level.")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducible tile sampling and noise.")
    parser.add_argument("--overwrite", action="store_true", help="Delete the output dataset directory if it already exists.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rng = random.Random(args.seed)
    np_rng = np.random.default_rng(args.seed)

    config = NavConfig()
    if args.collection_id:
        config.maps.active_collection_id = args.collection_id

    collection_root = resolve_collection_root(config)
    if collection_root is None:
        raise SystemExit("no tile collection found")

    collection_id = collection_root.name
    dataset_root = Path(args.output_root)
    if not dataset_root.is_absolute():
        dataset_root = (REPO_ROOT / dataset_root).resolve()
    dataset_root = dataset_root / f"{collection_id}-synth"

    if dataset_root.exists():
        if not args.overwrite:
            raise SystemExit(f"dataset already exists: {dataset_root} (use --overwrite to replace it)")
        shutil.rmtree(dataset_root)

    queries_root = dataset_root / "queries"
    queries_root.mkdir(parents=True, exist_ok=True)

    tiles = discover_tiles(collection_root)
    if not tiles:
        raise SystemExit(f"no PNG tiles found under: {collection_root}")

    grouped = group_tiles_by_zoom(tiles)
    cases: list[dict[str, object]] = []
    sample_count = max(1, args.count_per_zoom)

    for zoom, zoom_tiles in sorted(grouped.items()):
        chosen = rng.sample(zoom_tiles, k=min(sample_count, len(zoom_tiles)))
        for tile in chosen:
            image = cv2.imread(str(tile["path"]), cv2.IMREAD_COLOR)
            if image is None:
                continue
            for transform in transform_specs():
                synthetic = apply_transform(image, transform, np_rng)
                file_name = (
                    f"z{tile['zoom']}_x{tile['x']}_y{tile['y']}__{transform['id']}.png"
                )
                condition_dir = queries_root / transform["id"]
                condition_dir.mkdir(parents=True, exist_ok=True)
                out_path = condition_dir / file_name
                cv2.imwrite(str(out_path), synthetic)

                north, south, west, east = tile_bounds(tile["zoom"], tile["x"], tile["y"])
                lat_center = (north + south) * 0.5
                lon_center = (west + east) * 0.5
                mpp = tile_meters_per_pixel(tile["zoom"], lat_center)
                altitude_m = estimate_altitude_m(
                    width_px=image.shape[1],
                    meters_per_pixel=mpp,
                    fov_deg=config.camera.down_fov_deg,
                )

                cases.append(
                    {
                        "image_rel_path": out_path.relative_to(dataset_root).as_posix(),
                        "condition": transform["id"],
                        "transform": transform,
                        "collection_id": collection_id,
                        "source_tile_rel_path": tile["path"].relative_to(collection_root).as_posix(),
                        "zoom": tile["zoom"],
                        "x": tile["x"],
                        "y": tile["y"],
                        "expected_lat": lat_center,
                        "expected_lon": lon_center,
                        "seed_lat": lat_center,
                        "seed_lon": lon_center,
                        "altitude_m": altitude_m,
                        "yaw_deg": 0.0,
                        "meters_per_pixel": mpp,
                    }
                )

    manifest = {
        "dataset_id": dataset_root.name,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection_id": collection_id,
        "source_collection_root": str(collection_root),
        "count_per_zoom": sample_count,
        "random_seed": args.seed,
        "camera_fov_deg": config.camera.down_fov_deg,
        "cases": cases,
    }
    (dataset_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"dataset={dataset_root}")
    print(f"collection_id={collection_id}")
    print(f"cases={len(cases)}")
    print(f"conditions={len(transform_specs())}")


def resolve_collection_root(config: NavConfig) -> Path | None:
    root = config.maps.collections_root
    if not root.exists():
        return None
    if config.maps.active_collection_id:
        candidate = root / config.maps.active_collection_id
        return candidate if candidate.exists() else None
    candidates = [path for path in root.iterdir() if path.is_dir() and (path / "tiles").exists()]
    if not candidates:
        return None
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return candidates[0]


def discover_tiles(collection_root: Path) -> list[dict[str, object]]:
    tiles: list[dict[str, object]] = []
    for path in sorted((collection_root / "tiles").rglob("*.png")):
        rel = path.relative_to(collection_root / "tiles")
        if len(rel.parts) != 3:
            continue
        zoom, x, file_name = rel.parts
        try:
            y = int(Path(file_name).stem)
            tiles.append(
                {
                    "path": path,
                    "zoom": int(zoom),
                    "x": int(x),
                    "y": y,
                }
            )
        except ValueError:
            continue
    return tiles


def group_tiles_by_zoom(tiles: list[dict[str, object]]) -> dict[int, list[dict[str, object]]]:
    grouped: dict[int, list[dict[str, object]]] = {}
    for tile in tiles:
        grouped.setdefault(int(tile["zoom"]), []).append(tile)
    return grouped


def transform_specs() -> list[dict[str, object]]:
    return [
        {"id": "clean", "rotate_deg": 0.0, "noise_sigma": 0.0, "flip_code": None},
        {"id": "noise_08", "rotate_deg": 0.0, "noise_sigma": 8.0, "flip_code": None},
        {"id": "noise_16", "rotate_deg": 0.0, "noise_sigma": 16.0, "flip_code": None},
        {"id": "noise_24", "rotate_deg": 0.0, "noise_sigma": 24.0, "flip_code": None},
        {"id": "rotate_05", "rotate_deg": 5.0, "noise_sigma": 0.0, "flip_code": None},
        {"id": "rotate_10", "rotate_deg": 10.0, "noise_sigma": 0.0, "flip_code": None},
        {"id": "rotate_20", "rotate_deg": 20.0, "noise_sigma": 0.0, "flip_code": None},
        {"id": "flip_h", "rotate_deg": 0.0, "noise_sigma": 0.0, "flip_code": 1},
        {"id": "flip_v", "rotate_deg": 0.0, "noise_sigma": 0.0, "flip_code": 0},
        {"id": "flip_hv", "rotate_deg": 0.0, "noise_sigma": 0.0, "flip_code": -1},
        {"id": "rotate_10_noise_12", "rotate_deg": 10.0, "noise_sigma": 12.0, "flip_code": None},
        {"id": "rotate_20_noise_20", "rotate_deg": 20.0, "noise_sigma": 20.0, "flip_code": None},
    ]


def apply_transform(image, spec: dict[str, object], np_rng: np.random.Generator):
    transformed = image.copy()
    rotate_deg = float(spec["rotate_deg"])
    if abs(rotate_deg) > 1e-6:
        h, w = transformed.shape[:2]
        matrix = cv2.getRotationMatrix2D((w * 0.5, h * 0.5), rotate_deg, 1.0)
        transformed = cv2.warpAffine(
            transformed,
            matrix,
            (w, h),
            flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REFLECT_101,
        )

    flip_code = spec["flip_code"]
    if flip_code is not None:
        transformed = cv2.flip(transformed, int(flip_code))

    noise_sigma = float(spec["noise_sigma"])
    if noise_sigma > 0.0:
        noise = np_rng.normal(0.0, noise_sigma, size=transformed.shape).astype(np.float32)
        transformed = np.clip(transformed.astype(np.float32) + noise, 0.0, 255.0).astype(np.uint8)

    return transformed


def estimate_altitude_m(width_px: int, meters_per_pixel: float, fov_deg: float) -> float:
    ground_width_m = max(1e-6, width_px * meters_per_pixel)
    return (ground_width_m * 0.5) / math.tan(math.radians(fov_deg) * 0.5)


if __name__ == "__main__":
    main()
