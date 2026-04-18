from __future__ import annotations

import csv
import statistics
from pathlib import Path


class BenchmarkLogger:
    def __init__(self, output_path: str | Path = "benchmark_log.csv") -> None:
        self._output_path = Path(output_path)
        self._rows: list[tuple[float, str, float]] = []

    def log_inference(self, inference_ms: float, terrain_class: str, confidence: float) -> None:
        self._rows.append((inference_ms, terrain_class, confidence))

    def get_stats(self) -> dict[str, float]:
        if not self._rows:
            return {"mean_ms": 0.0, "min_ms": 0.0, "max_ms": 0.0, "std_ms": 0.0, "total_inferences": 0}
        samples = [row[0] for row in self._rows]
        return {
            "mean_ms": statistics.mean(samples),
            "min_ms": min(samples),
            "max_ms": max(samples),
            "std_ms": statistics.pstdev(samples) if len(samples) > 1 else 0.0,
            "total_inferences": len(samples),
        }

    def dump_csv(self, path: str | Path | None = None) -> None:
        target = Path(path) if path else self._output_path
        with target.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["inference_ms", "class", "confidence"])
            writer.writerows(self._rows)

