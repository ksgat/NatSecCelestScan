from __future__ import annotations

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import cv2
import numpy as np

import sys

SRC_ROOT = Path(__file__).resolve().parents[1]
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from pnt.config import NavConfig
from pnt.camera import CameraCapture


def encode_jpeg(frame) -> bytes:
    ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()


def placeholder_frame(label: str, width: int = 640, height: int = 480):
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    cv2.putText(frame, label, (20, height // 2), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 0, 255), 2, cv2.LINE_AA)
    return frame


def annotate_frame(frame, label: str):
    annotated = frame.copy()
    cv2.putText(
        annotated,
        f"{label} {time.strftime('%H:%M:%S')}",
        (10, 25),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 255, 0),
        2,
        cv2.LINE_AA,
    )
    return annotated


def build_status(cam0: CameraCapture, cam1: CameraCapture) -> str:
    s0 = cam0.status()
    s1 = cam1.status()
    return (
        f"cam0 ({s0.label} /dev/video{s0.camera_id}): ok={s0.ok} error={s0.error} size={s0.width}x{s0.height} fps={s0.fps:.2f}\n"
        f"cam1 ({s1.label} /dev/video{s1.camera_id}): ok={s1.ok} error={s1.error} size={s1.width}x{s1.height} fps={s1.fps:.2f}\n"
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
        if frame is None:
            return placeholder_frame("cam0 unavailable")
        return annotate_frame(frame, f"{type(self).cam0.label} /dev/video{type(self).cam0.camera_id}")

    def _cam1_frame(self):
        frame = type(self).cam1.get_frame()
        if frame is None:
            return placeholder_frame("cam1 unavailable")
        return annotate_frame(frame, f"{type(self).cam1.label} /dev/video{type(self).cam1.camera_id}")

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
  <p>Defaults come from <code>pnt.config.NavConfig</code>.</p>
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
    cfg = NavConfig()
    parser = argparse.ArgumentParser(description="Simple HTTP camera debug server.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--cam0", type=int, default=cfg.camera.cam0_id)
    parser.add_argument("--cam1", type=int, default=cfg.camera.cam1_id)
    parser.add_argument("--width", type=int, default=cfg.camera.width)
    parser.add_argument("--height", type=int, default=cfg.camera.height)
    args = parser.parse_args()

    cam0_label = f"cam0:{cfg.camera.cam0_label}"
    cam1_label = f"cam1:{cfg.camera.cam1_label}"
    cam0 = CameraCapture(args.cam0, cam0_label, args.width, args.height, cfg.camera.poll_interval_s)
    cam1 = CameraCapture(args.cam1, cam1_label, args.width, args.height, cfg.camera.poll_interval_s)
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
