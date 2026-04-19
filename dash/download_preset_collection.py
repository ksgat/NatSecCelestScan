from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

import requests

import app as dashboard_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download a square tile collection from a dashboard source preset.")
    parser.add_argument(
        "--source-id",
        default=dashboard_app.DEFAULT_SOURCE_ID,
        help="Source preset id from dash/app.py",
    )
    parser.add_argument(
        "--miles",
        type=float,
        default=1.0,
        help="Square width in miles around the preset center.",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Optional collection name. Defaults to <source-id>-<miles>mi.",
    )
    parser.add_argument(
        "--collection-id",
        default="",
        help="Optional explicit collection id. If it already exists, missing tiles will be resumed into it.",
    )
    parser.add_argument(
        "--center-lat",
        type=float,
        default=None,
        help="Override preset center latitude.",
    )
    parser.add_argument(
        "--center-lon",
        type=float,
        default=None,
        help="Override preset center longitude.",
    )
    parser.add_argument(
        "--min-zoom",
        type=int,
        default=None,
        help="Override preset min zoom.",
    )
    parser.add_argument(
        "--max-zoom",
        type=int,
        default=None,
        help="Override preset max zoom.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = next((item for item in dashboard_app.SOURCE_PRESETS if item["id"] == args.source_id), None)
    if source is None:
        raise SystemExit(f"unknown source preset: {args.source_id}")

    center = source["default_center"]
    center_lat = float(args.center_lat if args.center_lat is not None else center["lat"])
    center_lon = float(args.center_lon if args.center_lon is not None else center["lon"])
    min_zoom = int(args.min_zoom if args.min_zoom is not None else source["default_min_zoom"])
    max_zoom = int(args.max_zoom if args.max_zoom is not None else source["default_max_zoom"])
    if min_zoom > max_zoom:
        min_zoom, max_zoom = max_zoom, min_zoom

    half_miles = max(0.05, args.miles / 2.0)
    lat_delta = miles_to_lat_degrees(half_miles)
    lon_delta = miles_to_lon_degrees(half_miles, center_lat)
    bbox = dashboard_app.BoundingBox(
        north=center_lat + lat_delta,
        south=center_lat - lat_delta,
        east=center_lon + lon_delta,
        west=center_lon - lon_delta,
    )
    tile_count = dashboard_app.estimate_tile_count(bbox, min_zoom, max_zoom)
    if tile_count > dashboard_app.MAX_TILE_DOWNLOAD:
        raise SystemExit(
            f"selection too large: {tile_count} tiles exceeds dashboard limit of {dashboard_app.MAX_TILE_DOWNLOAD}"
        )

    base_name = args.name.strip() or f"{source['id']}-{format_miles(args.miles)}mi"
    slug = dashboard_app.slugify_name(base_name)
    collection_id = args.collection_id.strip() or f"{slug}-{uuid.uuid4().hex[:8]}"
    metadata = dashboard_app.CollectionMetadata(
        collection_id=collection_id,
        name=base_name,
        bbox=bbox,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        tile_count=tile_count,
        tile_url_template=source["tile_url_template"],
        created_at=time.time(),
    )

    dashboard_app.ensure_data_dirs()
    dashboard_app.save_collection_metadata(metadata)
    session = requests.Session()
    session.headers.update({"User-Agent": dashboard_app.DEFAULT_USER_AGENT})

    downloaded = 0
    for zoom, x, y in dashboard_app.iter_tiles_for_bbox(bbox, min_zoom, max_zoom):
        target = dashboard_app.tile_file_path(collection_id, zoom, x, y)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            downloaded += 1
            continue
        url = metadata.tile_url_template.format(z=zoom, x=x, y=y)
        response = session.get(url, timeout=20)
        response.raise_for_status()
        target.write_bytes(response.content)
        downloaded += 1
        if downloaded % 25 == 0 or downloaded == tile_count:
            print(f"downloaded {downloaded}/{tile_count} tiles", flush=True)
        time.sleep(dashboard_app.REQUEST_DELAY_S)

    print(f"collection_id={collection_id}")
    print(f"name={base_name}")
    print(f"source={source['name']}")
    print(f"center=({center_lat:.6f}, {center_lon:.6f})")
    print(f"bbox={bbox.north:.6f},{bbox.south:.6f},{bbox.east:.6f},{bbox.west:.6f}")
    print(f"zooms={min_zoom}-{max_zoom}")
    print(f"tiles={tile_count}")


def miles_to_lat_degrees(miles: float) -> float:
    return miles / 69.0


def miles_to_lon_degrees(miles: float, latitude: float) -> float:
    import math

    return miles / (max(0.1, math.cos(latitude * math.pi / 180.0)) * 69.172)


def format_miles(value: float) -> str:
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return text.replace(".", "p")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
