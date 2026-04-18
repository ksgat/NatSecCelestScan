from __future__ import annotations

import time


class ServoController:
    def __init__(self, min_seconds_between_flips: float = 3.0) -> None:
        self._position = "DOWN"
        self._last_flip = 0.0
        self._min_seconds_between_flips = min_seconds_between_flips

    def flip_camera(self, direction: str) -> bool:
        direction = direction.upper()
        now = time.time()
        if direction not in {"UP", "DOWN"}:
            raise ValueError(f"unsupported direction: {direction}")
        if direction == self._position:
            return True
        if now - self._last_flip < self._min_seconds_between_flips:
            return False
        self._position = direction
        self._last_flip = now
        time.sleep(0.5)
        return True

    def get_position(self) -> str:
        return self._position

