wfrom __future__ import annotations

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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
            return None if self._frame is None else self._frame.copy()

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


def build_status(cam0: CameraStream, cam1: CameraStream) -> str:
    s0 = cam0.status()
    s1 = cam1.status()
    return (
        f"cam0: ok={s0['ok']} error={s0['error']} size={s0['width']}x{s0['height']}\n"
        f"cam1: ok={s1['ok']} error={s1['error']} size={s1['width']}x{s1['height']}\n"
        f"time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )


class CameraDebugHandler(BaseHTTPRequestHandler):
    cam0 = None
    cam1 = None

    def do_GET(self) -> None:
        if self.path == "/":
            self._send_html(self._index_html())
            return
        if self.path == "/health":
            self._send_text(build_status(type(self).cam0, type(self).cam1))
            return
        if self.path == "/cam0.jpg":
            self._send_jpeg(self._cam0_frame())
            return
        if self.path == "/cam1.jpg":
            self._send_jpeg(self._cam1_frame())
            return
        if self.path == "/stereo.jpg":
            self._send_jpeg(self._stereo_frame())
            return
        if self.path == "/stream/cam0":
            self._send_mjpeg(self._cam0_frame)
            return
        if self.path == "/stream/cam1":
            self._send_mjpeg(self._cam1_frame)
            return
        if self.path == "/stream/stereo":
            self._send_mjpeg(self._stereo_frame)
            return
        self.send_error(404, "not found")

    def log_message(self, format: str, *args) -> None:
        return

    def _cam0_frame(self):
        frame = type(self).cam0.get_frame()
        return frame if frame is not None else placeholder_frame("cam0 unavailable")

    def _cam1_frame(self):
        frame = type(self).cam1.get_frame()
        return frame if frame is not None else placeholder_frame("cam1 unavailable")

    def _stereo_frame(self):
        left = type(self).cam0.get_frame()
        right = type(self).cam1.get_frame()
        if left is None and right is None:
            return placeholder_frame("both cameras unavailable")
        if left is None:
            left = placeholder_frame("cam0 unavailable", type(self).cam0.width, type(self).cam0.height)
        if right is None:
            right = placeholder_frame("cam1 unavailable", type(self).cam1.width, type(self).cam1.height)
        return np.hstack([left, right])

    def _send_html(self, html: str) -> None:
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, text: str) -> None:
        body = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_jpeg(self, frame) -> None:
        body = encode_jpeg(frame)
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_mjpeg(self, frame_provider) -> None:
        boundary = "frame"
        self.send_response(200)
        self.send_header("Age", "0")
        self.send_header("Cache-Control", "no-cache, private")
        self.send_header("Pragma", "no-cache")
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary=--{boundary}")
        self.end_headers()
        try:
            while True:
                frame = frame_provider()
                jpg = encode_jpeg(frame)
                self.wfile.write(f"--{boundary}\r\n".encode("ascii"))
                self.wfile.write(b"Content-Type: image/jpeg\r\n")
                self.wfile.write(f"Content-Length: {len(jpg)}\r\n\r\n".encode("ascii"))
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                time.sleep(0.08)
        except (BrokenPipeError, ConnectionResetError):
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
</head>
<body>
  <h1>Camera Debug</h1>
  <p>Still images: <code>/cam0.jpg</code> <code>/cam1.jpg</code> <code>/stereo.jpg</code></p>
  <p>MJPEG streams: <code>/stream/cam0</code> <code>/stream/cam1</code> <code>/stream/stereo</code></p>
  <p><a href="/health" target="_blank">health</a></p>
  <div class="grid">
    <div class="card"><h2>cam0</h2><img src="/stream/cam0" alt="cam0"></div>
    <div class="card"><h2>cam1</h2><img src="/stream/cam1" alt="cam1"></div>
    <div class="card"><h2>stereo</h2><img src="/stream/stereo" alt="stereo"></div>
  </div>
</body>
</html>
"""


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
    CameraDebugHandler.cam0 = cam0
    CameraDebugHandler.cam1 = cam1

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
