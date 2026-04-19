from __future__ import annotations

import threading
import time
from dataclasses import dataclass

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


@dataclass
class CameraStatus:
    camera_id: int
    label: str
    ok: bool
    error: str
    width: int
    height: int
    fps: float
    frame_timestamp: float


def open_camera(camera_id: int, width: int = 640, height: int = 480):
    if cv2 is None:
        raise RuntimeError("opencv-python is not installed")
    cap = cv2.VideoCapture(camera_id)
    if not cap.isOpened():
        raise RuntimeError(f"failed to open /dev/video{camera_id}")
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    return cap


def close_camera(cap) -> None:
    if cap is not None:
        cap.release()


def read_frame(cap):
    ok, frame = cap.read()
    if not ok or frame is None:
        raise RuntimeError("camera read failed")
    return frame, time.time()


class CameraCapture:
    def __init__(self, camera_id: int, label: str, width: int = 640, height: int = 480, poll_interval_s: float = 0.03) -> None:
        self.camera_id = camera_id
        self.label = label
        self.width = width
        self.height = height
        self.poll_interval_s = poll_interval_s
        self._cap = None
        self._lock = threading.Lock()
        self._frame = None
        self._frame_timestamp = 0.0
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_ok = False
        self._last_error = ""
        self._fps = 0.0
        self._last_frame_time = 0.0

    def start(self) -> None:
        if self._running:
            return
        self._cap = open_camera(self.camera_id, self.width, self.height)
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        close_camera(self._cap)
        self._cap = None

    def get_frame(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def get_frame_with_timestamp(self):
        with self._lock:
            if self._frame is None:
                return None, 0.0
            return self._frame.copy(), self._frame_timestamp

    def read_once(self):
        if self._cap is None:
            self._cap = open_camera(self.camera_id, self.width, self.height)
        frame, ts = read_frame(self._cap)
        self._record_frame(frame, ts)
        return frame

    def status(self) -> CameraStatus:
        with self._lock:
            return CameraStatus(
                camera_id=self.camera_id,
                label=self.label,
                ok=self._last_ok,
                error=self._last_error,
                width=self.width,
                height=self.height,
                fps=self._fps,
                frame_timestamp=self._frame_timestamp,
            )

    def _record_frame(self, frame, timestamp: float) -> None:
        fps = self._fps
        if self._last_frame_time > 0.0:
            dt = max(1e-6, timestamp - self._last_frame_time)
            inst_fps = 1.0 / dt
            fps = inst_fps if fps <= 0.0 else (0.85 * fps + 0.15 * inst_fps)
        self._last_frame_time = timestamp
        with self._lock:
            self._frame = frame
            self._frame_timestamp = timestamp
            self._fps = fps
            self._last_ok = True
            self._last_error = ""

    def _run(self) -> None:
        while self._running:
            try:
                frame, ts = read_frame(self._cap)
                self._record_frame(frame, ts)
            except Exception as exc:
                with self._lock:
                    self._last_ok = False
                    self._last_error = str(exc)
            time.sleep(self.poll_interval_s)
