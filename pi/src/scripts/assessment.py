from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    import cv2
except ImportError as exc:  # pragma: no cover
    raise SystemExit("opencv-python is required for assessment.py") from exc


REPO_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pnt.config import NavConfig
from pnt.embedding_backend import build_embedding_backend
from pnt.geo_match import GeoMatcher
from pnt.map_manager import MapManager, haversine_m
from pnt.models import Attitude


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Assess geo-match performance over a synthetic test manifest.")
    parser.add_argument(
        "--manifest",
        default="",
        help="Path to a synthetic dataset manifest. Defaults to the latest manifest under test_images/ground/synthetic.",
    )
    parser.add_argument(
        "--output-root",
        default=str(REPO_ROOT / "pi" / "src" / "assets" / "test_images" / "ground" / "synthetic"),
        help="Root where synthetic datasets live when --manifest is not provided.",
    )
    parser.add_argument(
        "--pass-threshold-m",
        type=float,
        default=50.0,
        help="Distance threshold in meters for a pass/fail summary.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of the text summary.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_path = resolve_manifest_path(args)
    dataset_root = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    config = NavConfig()
    config.maps.active_collection_id = str(manifest["collection_id"])
    backend = build_embedding_backend(config.maps.embedding_model_name, config.maps.embedding_device)
    maps = MapManager(config.root_dir, config.mission_bounds, config.maps)
    matcher = GeoMatcher(maps, backend, config.maps)

    cases_out = []
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for case in manifest["cases"]:
        image_path = dataset_root / case["image_rel_path"]
        frame = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
        if frame is None:
            continue
        result = matcher.update(
            frame=frame,
            altitude_m=float(case["altitude_m"]),
            attitude=Attitude(yaw=float(case.get("yaw_deg", 0.0))),
            seed_lat=float(case["seed_lat"]),
            seed_lon=float(case["seed_lon"]),
        )
        error_m = haversine_m(
            float(case["expected_lat"]),
            float(case["expected_lon"]),
            result.lat,
            result.lon,
        )
        row = {
            "image_rel_path": case["image_rel_path"],
            "condition": case["condition"],
            "zoom": int(case["zoom"]),
            "expected_lat": float(case["expected_lat"]),
            "expected_lon": float(case["expected_lon"]),
            "result_lat": float(result.lat),
            "result_lon": float(result.lon),
            "valid": bool(result.valid),
            "verified": bool(result.verified),
            "confidence": float(result.confidence),
            "structural_score": float(result.structural_score),
            "inlier_count": int(result.inlier_count),
            "match_score": float(result.match_score),
            "scale_error": float(result.scale_error),
            "error_m": float(error_m),
            "pass": bool(result.valid and error_m <= args.pass_threshold_m),
            "tile_path": result.tile_path,
        }
        cases_out.append(row)
        grouped[row["condition"]].append(row)

    summary = summarize(grouped, args.pass_threshold_m)
    payload = {
        "manifest": str(manifest_path),
        "evaluated_at_utc": datetime.now(timezone.utc).isoformat(),
        "collection_id": manifest["collection_id"],
        "pass_threshold_m": args.pass_threshold_m,
        "backend": backend.status().__dict__,
        "summary": summary,
        "cases": cases_out,
    }

    (dataset_root / "assessment.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    write_case_csv(dataset_root / "assessment_cases.csv", cases_out)
    write_summary_csv(dataset_root / "assessment_summary.csv", summary)

    if args.json:
        print(json.dumps(payload, indent=2))
        return

    print(f"manifest={manifest_path}")
    print(f"collection={manifest['collection_id']}")
    print(f"backend={payload['backend']['model_name']} available={payload['backend']['available']}")
    print(f"pass_threshold_m={args.pass_threshold_m:.1f}")
    for row in summary:
        print(
            f"{row['condition']}: "
            f"count={row['count']} "
            f"valid_rate={row['valid_rate']:.2f} "
            f"verified_rate={row['verified_rate']:.2f} "
            f"pass_rate={row['pass_rate']:.2f} "
            f"avg_error_m={row['avg_error_m']:.1f} "
            f"avg_conf={row['avg_confidence']:.2f} "
            f"avg_struct={row['avg_structural_score']:.2f}"
        )
    print(f"wrote={dataset_root / 'assessment.json'}")


def resolve_manifest_path(args: argparse.Namespace) -> Path:
    if args.manifest:
        manifest_path = Path(args.manifest)
        if not manifest_path.is_absolute():
            manifest_path = (REPO_ROOT / manifest_path).resolve()
        if not manifest_path.exists():
            raise SystemExit(f"manifest not found: {manifest_path}")
        return manifest_path

    output_root = Path(args.output_root)
    if not output_root.is_absolute():
        output_root = (REPO_ROOT / output_root).resolve()
    manifests = sorted(output_root.rglob("manifest.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not manifests:
        raise SystemExit(f"no manifest found under: {output_root}")
    return manifests[0]


def summarize(grouped: dict[str, list[dict[str, object]]], pass_threshold_m: float) -> list[dict[str, object]]:
    summary = []
    for condition, rows in sorted(grouped.items()):
        count = len(rows)
        valid_rate = sum(1 for row in rows if row["valid"]) / count
        verified_rate = sum(1 for row in rows if row["verified"]) / count
        pass_rate = sum(1 for row in rows if row["pass"]) / count
        summary.append(
            {
                "condition": condition,
                "count": count,
                "pass_threshold_m": pass_threshold_m,
                "valid_rate": valid_rate,
                "verified_rate": verified_rate,
                "pass_rate": pass_rate,
                "avg_error_m": mean_or_zero(row["error_m"] for row in rows),
                "median_error_m": median_or_zero(row["error_m"] for row in rows),
                "avg_confidence": mean_or_zero(row["confidence"] for row in rows),
                "avg_structural_score": mean_or_zero(row["structural_score"] for row in rows),
                "avg_inlier_count": mean_or_zero(row["inlier_count"] for row in rows),
            }
        )
    return summary


def write_case_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_summary_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def mean_or_zero(values) -> float:
    seq = list(values)
    return float(statistics.fmean(seq)) if seq else 0.0


def median_or_zero(values) -> float:
    seq = list(values)
    return float(statistics.median(seq)) if seq else 0.0


if __name__ == "__main__":
    main()
