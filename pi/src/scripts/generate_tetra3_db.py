from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a tetra3 database matched to the configured camera FOV.")
    parser.add_argument(
        "--config",
        default=str(Path(__file__).resolve().parents[1] / "assets" / "config" / "star_solver.json"),
        help="Path to the star solver config JSON.",
    )
    parser.add_argument(
        "--catalog-dir",
        required=True,
        help="Directory containing the source catalog file for tetra3 (e.g. tyc_main.dat).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional output path for the generated database. Defaults to the configured primary database path.",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    config_path = Path(args.config).resolve()
    config = json.loads(config_path.read_text(encoding="utf-8"))
    assets_root = config_path.parents[1]
    src_root = assets_root.parent
    tetra3_pkg = src_root / "tetra3"

    if not tetra3_pkg.exists():
        raise FileNotFoundError(f"vendored tetra3 package not found at {tetra3_pkg}")

    sys.path.insert(0, str(src_root))
    from tetra3 import Tetra3  # type: ignore

    generation = dict(config.get("database_generation", {}))
    output = Path(args.output) if args.output else (src_root / config["database"])
    output.parent.mkdir(parents=True, exist_ok=True)

    catalog_dir = Path(args.catalog_dir).resolve()
    if not catalog_dir.exists():
        raise FileNotFoundError(f"catalog directory not found: {catalog_dir}")

    solver = Tetra3()
    old_cwd = Path.cwd()
    try:
        import os

        # tetra3 resolves catalogs relative to tetra3.py. Keep a copy in the vendored
        # package so the generator works without an external checkout.
        catalog_name = str(generation.get("star_catalog", "tyc_main"))
        source_catalog = catalog_dir / catalog_name
        if catalog_name in {"hip_main", "tyc_main"} and source_catalog.suffix == "":
            source_catalog = source_catalog.with_suffix(".dat")
        vendored_catalog = tetra3_pkg / source_catalog.name
        if source_catalog.resolve() != vendored_catalog.resolve():
            import shutil

            shutil.copy2(source_catalog, vendored_catalog)
        os.chdir(src_root)
        solver.generate_database(
            max_fov=float(generation.get("max_fov", config["fov_estimate"])),
            save_as=str(output),
            star_catalog=catalog_name,
            pattern_stars_per_fov=int(generation.get("pattern_stars_per_fov", 10)),
            verification_stars_per_fov=int(generation.get("verification_stars_per_fov", 20)),
            star_max_magnitude=float(generation.get("star_max_magnitude", 7.0)),
        )
    finally:
        os.chdir(old_cwd)

    print(f"generated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
