from __future__ import annotations

import time

from .models import PoseEstimate


def _checksum(sentence_body: str) -> str:
    checksum = 0
    for char in sentence_body:
        checksum ^= ord(char)
    return f"{checksum:02X}"


def _format_lat(lat: float) -> tuple[str, str]:
    hemisphere = "N" if lat >= 0 else "S"
    lat = abs(lat)
    degrees = int(lat)
    minutes = (lat - degrees) * 60.0
    return f"{degrees:02d}{minutes:07.4f}", hemisphere


def _format_lon(lon: float) -> tuple[str, str]:
    hemisphere = "E" if lon >= 0 else "W"
    lon = abs(lon)
    degrees = int(lon)
    minutes = (lon - degrees) * 60.0
    return f"{degrees:03d}{minutes:07.4f}", hemisphere


def format_gpgga(pose: PoseEstimate, fix_quality: int, satellites: int = 8) -> str:
    hhmmss = time.strftime("%H%M%S", time.gmtime())
    lat, lat_hemi = _format_lat(pose.lat)
    lon, lon_hemi = _format_lon(pose.lon)
    body = f"GPGGA,{hhmmss},{lat},{lat_hemi},{lon},{lon_hemi},{fix_quality},{satellites},1.0,{pose.alt_m:.1f},M,,,"
    return f"${body}*{_checksum(body)}"


def format_gprmc(pose: PoseEstimate, valid: bool = True, speed_knots: float = 0.0) -> str:
    tm = time.gmtime()
    hhmmss = time.strftime("%H%M%S", tm)
    ddmmyy = time.strftime("%d%m%y", tm)
    lat, lat_hemi = _format_lat(pose.lat)
    lon, lon_hemi = _format_lon(pose.lon)
    status = "A" if valid else "V"
    body = f"GPRMC,{hhmmss},{status},{lat},{lat_hemi},{lon},{lon_hemi},{speed_knots:.1f},{pose.heading_deg:.1f},{ddmmyy},,,"
    return f"${body}*{_checksum(body)}"


def validate_checksum(sentence: str) -> bool:
    if not sentence.startswith("$") or "*" not in sentence:
        return False
    body, given = sentence[1:].split("*", 1)
    return _checksum(body) == given.strip().upper()

