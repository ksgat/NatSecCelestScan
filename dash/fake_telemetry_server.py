from __future__ import annotations

import argparse
import json
import math
import socket
import time


def checksum(sentence_body: str) -> str:
    value = 0
    for char in sentence_body:
        value ^= ord(char)
    return f"{value:02X}"


def format_lat(lat: float) -> tuple[str, str]:
    hemisphere = "N" if lat >= 0 else "S"
    lat = abs(lat)
    degrees = int(lat)
    minutes = (lat - degrees) * 60.0
    return f"{degrees:02d}{minutes:07.4f}", hemisphere


def format_lon(lon: float) -> tuple[str, str]:
    hemisphere = "E" if lon >= 0 else "W"
    lon = abs(lon)
    degrees = int(lon)
    minutes = (lon - degrees) * 60.0
    return f"{degrees:03d}{minutes:07.4f}", hemisphere


def format_gpgga(lat: float, lon: float, alt_m: float, fix_quality: int = 1, satellites: int = 10) -> str:
    hhmmss = time.strftime("%H%M%S", time.gmtime())
    lat_value, lat_hemi = format_lat(lat)
    lon_value, lon_hemi = format_lon(lon)
    body = (
        f"GPGGA,{hhmmss},{lat_value},{lat_hemi},{lon_value},{lon_hemi},"
        f"{fix_quality},{satellites},0.9,{alt_m:.1f},M,,,"
    )
    return f"${body}*{checksum(body)}"


def format_gprmc(lat: float, lon: float, heading_deg: float, speed_knots: float, valid: bool = True) -> str:
    tm = time.gmtime()
    hhmmss = time.strftime("%H%M%S", tm)
    ddmmyy = time.strftime("%d%m%y", tm)
    lat_value, lat_hemi = format_lat(lat)
    lon_value, lon_hemi = format_lon(lon)
    status = "A" if valid else "V"
    body = (
        f"GPRMC,{hhmmss},{status},{lat_value},{lat_hemi},{lon_value},{lon_hemi},"
        f"{speed_knots:.1f},{heading_deg:.1f},{ddmmyy},,,"
    )
    return f"${body}*{checksum(body)}"


def heading_from_velocity(vx: float, vy: float) -> float:
    heading = math.degrees(math.atan2(vx, vy))
    return (heading + 360.0) % 360.0


def build_debug_packet(*, now: float, lat: float, lon: float, alt_m: float, heading_deg: float, t: float) -> dict[str, object]:
    roll = 3.0 * math.sin(t * 0.7)
    pitch = 2.0 * math.cos(t * 0.55)
    yaw = heading_deg
    imu_ax = 0.03 * math.cos(t * 1.3)
    imu_ay = 0.02 * math.sin(t * 1.7)
    imu_az = 1.0 + 0.01 * math.sin(t * 0.4)
    imu_gx = 0.7 * math.sin(t * 0.9)
    imu_gy = 0.5 * math.cos(t * 1.1)
    imu_gz = 1.0 * math.sin(t * 0.8)
    confidence = 0.82 + 0.08 * math.sin(t * 0.25)
    return {
        "type": "nav_debug",
        "ts": now,
        "mode": "geo_match",
        "last_absolute_fix_age_s": 0.25,
        "pose": {
            "lat": lat,
            "lon": lon,
            "alt_m": alt_m,
            "heading_deg": heading_deg,
            "confidence": round(confidence, 3),
            "fix_type": "geo_match",
        },
        "attitude": {
            "roll": round(roll, 3),
            "pitch": round(pitch, 3),
            "yaw": round(yaw, 3),
        },
        "imu": {
            "ax": round(imu_ax, 4),
            "ay": round(imu_ay, 4),
            "az": round(imu_az, 4),
            "gx": round(imu_gx, 4),
            "gy": round(imu_gy, 4),
            "gz": round(imu_gz, 4),
            "temp": 31.5,
            "timestamp": now,
        },
        "stereo": {
            "valid": True,
            "altitude_m": alt_m,
            "center_depth_m": alt_m,
            "disparity_confidence": 0.91,
            "depth_variance": 0.08,
        },
        "vo": {
            "valid": True,
            "confidence": 0.77,
            "track_count": 152,
            "inlier_ratio": 0.68,
            "parallax_score": 0.43,
            "reprojection_error": 1.22,
        },
        "geo": {
            "valid": True,
            "verified": True,
            "confidence": round(confidence, 3),
            "candidate_count": 5,
            "inlier_count": 61,
            "structural_score": 0.74,
            "match_score": 0.79,
            "tile_path": "synthetic/fairfax/18/74778/100330.png",
        },
        "celestial": {
            "valid": False,
            "confidence": 0.0,
            "method": "disabled",
        },
        "terrain": {
            "terrain_class": "urban",
            "confidence": 0.88,
            "inference_ms": 18.5,
        },
        "confidence": {
            "confidence": round(confidence, 3),
            "fix_quality": 1,
            "fix_type": "geo_match",
        },
        "camera": {
            "cam0": {
                "camera_id": 0,
                "label": "servo",
                "ok": True,
                "error": "",
                "fps": 4.8,
                "frame_timestamp": now,
            },
            "cam1": {
                "camera_id": 2,
                "label": "fixed_down",
                "ok": True,
                "error": "",
                "fps": 5.0,
                "frame_timestamp": now,
            },
            "servo_position": "DOWN",
        },
        "map": {
            "collection_id": "fairfax-runtime-1mi-b6f538ab",
            "runtime_embeddings": False,
            "embedding_backend": "disabled",
            "embedding_backend_ok": False,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Emit fake NMEA and nav debug packets for the dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Dashboard host to send UDP packets to.")
    parser.add_argument("--nmea-port", type=int, default=10110, help="NMEA UDP port on the dashboard.")
    parser.add_argument("--debug-port", type=int, default=10111, help="Debug JSON UDP port on the dashboard.")
    parser.add_argument("--hz", type=float, default=2.0, help="Update rate in Hz.")
    parser.add_argument("--center-lat", type=float, default=38.8462, help="Center latitude for the fake track.")
    parser.add_argument("--center-lon", type=float, default=-77.3064, help="Center longitude for the fake track.")
    parser.add_argument("--radius-m", type=float, default=110.0, help="Track radius in meters.")
    parser.add_argument("--altitude-m", type=float, default=58.0, help="Reported altitude in meters.")
    args = parser.parse_args()

    nmea_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    debug_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    nmea_target = (args.host, args.nmea_port)
    debug_target = (args.host, args.debug_port)
    period = 1.0 / max(args.hz, 0.1)
    meters_per_deg_lat = 111320.0
    meters_per_deg_lon = math.cos(math.radians(args.center_lat)) * 111320.0

    print(
        f"fake telemetry -> nmea udp://{args.host}:{args.nmea_port} "
        f"debug udp://{args.host}:{args.debug_port} hz={args.hz:.2f}"
    )
    try:
        while True:
            now = time.time()
            t = now * 0.12
            east_m = args.radius_m * math.cos(t)
            north_m = args.radius_m * math.sin(t)
            lat = args.center_lat + (north_m / meters_per_deg_lat)
            lon = args.center_lon + (east_m / meters_per_deg_lon)
            vx = -args.radius_m * math.sin(t)
            vy = args.radius_m * math.cos(t)
            heading_deg = heading_from_velocity(vx, vy)
            speed_mps = abs(args.radius_m * 0.12)
            speed_knots = speed_mps * 1.94384

            gga = format_gpgga(lat, lon, args.altitude_m)
            rmc = format_gprmc(lat, lon, heading_deg, speed_knots)
            debug_packet = build_debug_packet(
                now=now,
                lat=lat,
                lon=lon,
                alt_m=args.altitude_m,
                heading_deg=heading_deg,
                t=t,
            )

            nmea_socket.sendto(gga.encode("ascii"), nmea_target)
            nmea_socket.sendto(rmc.encode("ascii"), nmea_target)
            debug_socket.sendto(json.dumps(debug_packet).encode("utf-8"), debug_target)
            time.sleep(period)
    except KeyboardInterrupt:
        pass
    finally:
        nmea_socket.close()
        debug_socket.close()


if __name__ == "__main__":
    main()
