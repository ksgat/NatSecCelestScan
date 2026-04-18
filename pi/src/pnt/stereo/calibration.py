from __future__ import annotations

import json
from pathlib import Path


def run_calibration(cam0_id: int, cam1_id: int, output_path: str | Path) -> dict[str, object]:
    data = {
        "cam0_id": cam0_id,
        "cam1_id": cam1_id,
        "baseline_m": 0.12,
        "focal_length_px": 640.0,
    }
    path = Path(output_path)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data


def load_calibration(path: str | Path) -> dict[str, object]:
    return json.loads(Path(path).read_text(encoding="utf-8"))

