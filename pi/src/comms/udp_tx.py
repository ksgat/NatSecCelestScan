from __future__ import annotations

import json
import socket


class UdpTransmitter:
    def __init__(self, host: str, port: int) -> None:
        self._target = (host, port)
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    def set_target(self, ip: str, port: int) -> None:
        self._target = (ip, port)

    def transmit(self, nmea_str: str) -> None:
        self._socket.sendto(nmea_str.encode("ascii", errors="ignore"), self._target)

    def transmit_json(self, payload: dict[str, object]) -> None:
        self._socket.sendto(json.dumps(payload).encode("utf-8"), self._target)

    def close(self) -> None:
        self._socket.close()
