from __future__ import annotations

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

import cv2
import numpy as np


class CameraStream:
    def __init__(self, camera_id: int, width: int = 640, height: int = 480) -> None:
        self.camera_id = camera_id
        self.width = width
        self.height = height
        self._cap = cv2.VideoCapture(camera_id)
        self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self._lock = threading.Lock()
        self._frame = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._last_ok = False
        self._last_error = ""

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
        self._cap.release()

    def get_frame(self):
        with self._lock:
            if self._frame is None:
                return None
            return self._frame.copy()

    def status(self) -> dict[str, object]:
        return {
            "camera_id": self.camera_id,
            "ok": self._last_ok,
            "error": self._last_error,
            "width": self.width,
            "height": self.height,
        }

    def _run(self) -> None:
        while self._running:
            ok, frame = self._cap.read()
            if ok and frame is not None:
                annotated = frame.copy()
                cv2.putText(
                    annotated,
                    f"cam{self.camera_id} {time.strftime('%H:%M:%S')}",
                    (10, 25),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.7,
                    (0, 255, 0),
                    2,
                    cv2.LINE_AA,
                )
                with self._lock:
                    self._frame = annotated
                self._last_ok = True
                self._last_error = ""
            else:
                self._last_ok = False
                self._last_error = "read failed"
            time.sleep(0.03)


def encode_jpeg(frame) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


def placeholder_frame(label: str, width: int = 640, height: int = 480):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(frame, label, (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
    return frame


class CameraDebugHandler(BaseHTTPRequestHandler):
    routes: dict[str, Callable[[], bytes]] = {}
    status_provider: Callable[[], str] | None = None

    def do_GET(self) -> None:
        if self.path == "/":
            body = self._index_html().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if self.path == "/health":
            text = self.status_provider() if self.status_provider else "no status"
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        producer = self.routes.get(self.path)
        if producer is None:
            self.send_error(404, "not found")
            return

        body = producer()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args) -> None:
        return

    @staticmethod
    def _index_html() -> str:
        return """<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Camera Debug</title>
  <style>
    body { font-family: sans-serif; background: #111; color: #eee; margin: 20px; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }
    .card { background: #1b1b1b; padding: 12px; border-radius: 8px; }
    img { width: 100%; height: auto; border-radius: 4px; background: #000; }
    code { color: #8fd3ff; }
  </style>
  <script>
    function tick() {
      const ts = Date.now();
      document.getElementById('cam0').src = '/cam0.jpg?t=' + ts;
      document.getElementById('cam1').src = '/cam1.jpg?t=' + ts;
      document.getElementById('stereo').src = '/stereo.jpg?t=' + ts;
      fetch('/health').then(r => r.text()).then(t => document.getElementById('health').textContent = t);
    }
    setInterval(tick, 300);
    window.onload = tick;
  </script>
</head>
<body>
  <h1>Camera Debug</h1>
  <p>Endpoints: <code>/cam0.jpg</code> <code>/cam1.jpg</code> <code>/stereo.jpg</code> <code>/health</code></p>
  <pre id="health">loading...</pre>
  <div class="grid">
    <div class="card"><h2>cam0</h2><img id="cam0" alt="cam0"></div>
    <div class="card"><h2>cam1</h2><img id="cam1" alt="cam1"></div>
    <div class="card"><h2>stereo</h2><img id="stereo" alt="stereo"></div>
  </div>
</body>
</html>
"""


def build_status(cam0: CameraStream, cam1: CameraStream) -> str:
    s0 = cam0.status()
    s1 = cam1.status()
    return (
        f"cam0: ok={s0['ok']} error={s0['error']} size={s0['width']}x{s0['height']}\n"
        f"cam1: ok={s1['ok']} error={s1['error']} size={s1['width']}x{s1['height']}\n"
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Simple HTTP camera debug server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cam0", type=int, default=0)
    parser.add_argument("--cam1", type=int, default=1)
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    args = parser.parse_args()

    cam0 = CameraStream(args.cam0, args.width, args.height)
    cam1 = CameraStream(args.cam1, args.width, args.height)
    cam0.start()
    cam1.start()

    def cam0_jpg() -> bytes:
        frame = cam0.get_frame()
        return encode_jpeg(frame if frame is not None else placeholder_frame("cam0 unavailable"))

    def cam1_jpg() -> bytes:
        frame = cam1.get_frame()
        return encode_jpeg(frame if frame is not None else placeholder_frame("cam1 unavailable"))

    def stereo_jpg() -> bytes:
        left = cam0.get_frame()
        right = cam1.get_frame()
        if left is None and right is None:
            merged = placeholder_frame("both cameras unavailable")
        else:
            if left is None:
                left = placeholder_frame("cam0 unavailable", args.width, args.height)
            if right is None:
                right = placeholder_frame("cam1 unavailable", args.width, args.height)
            merged = np.hstack([left, right])
        return encode_jpeg(merged)

    CameraDebugHandler.routes = {
        "/cam0.jpg": cam0_jpg,
        "/cam1.jpg": cam1_jpg,
        "/stereo.jpg": stereo_jpg,
    }
    CameraDebugHandler.status_provider = lambda: build_status(cam0, cam1)

    server = ThreadingHTTPServer((args.host, args.port), CameraDebugHandler)
    print(f"camera debug server listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        cam0.stop()
        cam1.stop()


if __name__ == "__main__":
    main()
