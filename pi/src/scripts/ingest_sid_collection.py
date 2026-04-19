from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_ROOT = REPO_ROOT / "pi" / "src" / "assets"
DEFAULT_COLLECTION_ROOT = REPO_ROOT / "dash" / "data" / "collections"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a local XYZ tile collection from one MrSID file or a folder of MrSID tiles."
    )
    parser.add_argument(
        "source",
        help="Path to a .sid file or a directory containing .sid files (recursively scanned).",
    )
    parser.add_argument(
        "--collection-id",
        default="",
        help="Output collection id. Defaults to the source folder/file stem plus a timestamp.",
    )
    parser.add_argument(
        "--output-root",
        default=str(DEFAULT_COLLECTION_ROOT),
        help="Root folder where the tile collection should be written.",
    )
    parser.add_argument(
        "--zoom",
        default="17-19",
        help="XYZ zoom range passed to gdal2tiles, e.g. 16-19 or 18.",
    )
    parser.add_argument(
        "--tile-size",
        type=int,
        default=256,
        help="Tile size passed to gdal2tiles. Defaults to 256.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Delete an existing output collection with the same id before writing.",
    )
    parser.add_argument(
        "--keep-workdir",
        action="store_true",
        help="Keep the temporary VRT/GeoTIFF workdir for inspection.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source = Path(args.source)
    if not source.is_absolute():
        source = (REPO_ROOT / source).resolve()
    if not source.exists():
        raise SystemExit(f"source not found: {source}")

    sid_files = discover_sid_files(source)
    if not sid_files:
        raise SystemExit(f"no .sid files found under: {source}")

    collection_id = args.collection_id or build_collection_id(source)
    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = (REPO_ROOT / output_root).resolve()
    collection_root = output_root / collection_id

    if collection_root.exists():
        if not args.overwrite:
            raise SystemExit(f"collection already exists: {collection_root}")
        shutil.rmtree(collection_root)

    ensure_gdal()
    collection_root.mkdir(parents=True, exist_ok=True)

    workdir_parent = collection_root if args.keep_workdir else None
    with tempfile.TemporaryDirectory(prefix="sid_ingest_", dir=workdir_parent) as temp_dir:
        workdir = Path(temp_dir)
        vrt_path = workdir / "mosaic.vrt"
        tif_path = workdir / "mosaic.tif"
        tiles_path = collection_root / "tiles"

        build_vrt(vrt_path, sid_files)
        translate_to_geotiff(vrt_path, tif_path)
        tile_geotiff(tif_path, tiles_path, args.zoom, args.tile_size)

        metadata = build_metadata(
            source=source,
            sid_files=sid_files,
            collection_id=collection_id,
            zoom=args.zoom,
            tile_size=args.tile_size,
            tif_path=tif_path,
        )
        (collection_root / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

        if args.keep_workdir:
            print(f"kept intermediate workdir: {workdir}")

    print(f"created collection: {collection_root}")
    print(f"source sid count: {len(sid_files)}")
    print(f"zoom: {args.zoom}")


def discover_sid_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source] if source.suffix.lower() == ".sid" else []
    return sorted(path for path in source.rglob("*.sid") if path.is_file())


def build_collection_id(source: Path) -> str:
    base = source.stem if source.is_file() else source.name
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{base}-sid-{stamp}"


def ensure_gdal() -> None:
    required = ("gdalbuildvrt", "gdal_translate", "gdalinfo")
    missing = [command for command in required if shutil.which(command) is None]
    if missing:
        raise SystemExit(
            "missing GDAL tools: "
            + ", ".join(missing)
            + ". Install GDAL with MrSID support before running sid ingest."
        )


def build_vrt(vrt_path: Path, sid_files: list[Path]) -> None:
    command = ["gdalbuildvrt", str(vrt_path), *[str(path) for path in sid_files]]
    run(command, "failed to build VRT mosaic from MrSID sources")


def translate_to_geotiff(vrt_path: Path, tif_path: Path) -> None:
    command = [
        "gdal_translate",
        "-of",
        "GTiff",
        "-co",
        "TILED=YES",
        "-co",
        "COMPRESS=LZW",
        "-co",
        "BIGTIFF=IF_SAFER",
        str(vrt_path),
        str(tif_path),
    ]
    run(command, "failed to translate VRT mosaic to GeoTIFF")


def tile_geotiff(tif_path: Path, tiles_path: Path, zoom: str, tile_size: int) -> None:
    tiles_path.mkdir(parents=True, exist_ok=True)
    gdal2tiles_command = resolve_gdal2tiles_command()
    command = [
        *gdal2tiles_command,
        "--xyz",
        "--processes=1",
        "--tilesize",
        str(tile_size),
        "-z",
        zoom,
        str(tif_path),
        str(tiles_path),
    ]
    run(command, "failed to generate XYZ tiles from GeoTIFF")


def resolve_gdal2tiles_command() -> list[str]:
    if shutil.which("gdal2tiles.py") is not None:
        return ["gdal2tiles.py"]
    return [sys.executable, "-m", "osgeo_utils.gdal2tiles"]


def build_metadata(
    source: Path,
    sid_files: list[Path],
    collection_id: str,
    zoom: str,
    tile_size: int,
    tif_path: Path,
) -> dict[str, object]:
    gdalinfo = read_gdalinfo_json(tif_path)
    return {
        "collection_id": collection_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_type": "mrsid",
        "source_root": str(source),
        "source_sid_count": len(sid_files),
        "source_examples": [str(path) for path in sid_files[:8]],
        "zoom": zoom,
        "tile_size": tile_size,
        "tile_url_template": "local-sid-ingest",
        "gdal_driver": gdalinfo.get("driverShortName"),
        "size": gdalinfo.get("size"),
        "coordinate_system": gdalinfo.get("coordinateSystem"),
        "geo_transform": gdalinfo.get("geoTransform"),
        "wgs84_extent": gdalinfo.get("wgs84Extent"),
        "corner_coordinates": gdalinfo.get("cornerCoordinates"),
    }


def read_gdalinfo_json(dataset_path: Path) -> dict[str, object]:
    command = ["gdalinfo", "-json", str(dataset_path)]
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        return {}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}


def run(command: list[str], failure_message: str) -> None:
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode == 0:
        return

    message_parts = [failure_message]
    if completed.stdout.strip():
        message_parts.append(completed.stdout.strip())
    if completed.stderr.strip():
        message_parts.append(completed.stderr.strip())
    raise SystemExit("\n".join(message_parts))


if __name__ == "__main__":
    main()
