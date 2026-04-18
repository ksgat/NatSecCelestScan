from __future__ import annotations

import threading
import time

from .benchmark import BenchmarkLogger
from pnt.models import TerrainResult


class TerrainClassifier:
    def __init__(self) -> None:
        self._latest = TerrainResult("unknown", 0.0, 0.0)
        self._running = False
        self._thread: threading.Thread | None = None
        self._benchmark = BenchmarkLogger()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)

    def _run(self) -> None:
        classes = ["unknown", "urban", "vegetation", "water", "snow"]
        index = 0
        while self._running:
            start = time.perf_counter()
            terrain_class = classes[index % len(classes)]
            index += 1
            inference_ms = (time.perf_counter() - start) * 1000.0
            self._latest = TerrainResult(terrain_class, 0.5, inference_ms)
            self._benchmark.log_inference(inference_ms, terrain_class, 0.5)
            time.sleep(1.0)

    def get_latest_result(self) -> TerrainResult:
        return TerrainResult(self._latest.terrain_class, self._latest.confidence, self._latest.inference_ms)

    def get_stats(self) -> dict[str, float]:
        return self._benchmark.get_stats()

