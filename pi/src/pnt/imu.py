from __future__ import annotations

import threading
import time

from .models import Attitude, ImuReading


class ImuInterface:
    def __init__(self, sample_hz: float = 100.0) -> None:
        self._sample_hz = sample_hz
        self._reading = ImuReading(timestamp=time.time())
        self._attitude = Attitude()
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None

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
        period = 1.0 / self._sample_hz
        while self._running:
            now = time.time()
            with self._lock:
                self._reading.timestamp = now
            time.sleep(period)

    def get_reading(self) -> ImuReading:
        with self._lock:
            return ImuReading(**self._reading.__dict__)

    def get_attitude(self) -> Attitude:
        with self._lock:
            return Attitude(**self._attitude.__dict__)

