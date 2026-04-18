from __future__ import annotations


class SunSolver:
    def solve(self, frame) -> dict[str, object] | None:
        if frame is None:
            return None
        return {
            "valid": False,
            "confidence": 0.0,
            "method": "sun",
        }

