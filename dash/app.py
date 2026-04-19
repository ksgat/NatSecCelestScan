from __future__ import annotations

import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from flask import Flask, abort, jsonify, render_template, request, send_file


APP_ROOT = Path(__file__).resolve().parent
DATA_ROOT = APP_ROOT / "data"
COLLECTIONS_ROOT = DATA_ROOT / "collections"
EMBED_SCRIPT = APP_ROOT / "embed_tiles.py"
SOURCE_PRESETS = [
    {
        "id": "fairfax_2025",
        "name": "Fairfax 2025 Ortho",
        "tile_url_template": "https://www.fairfaxcounty.gov/gisimagery/rest/services/AerialPhotography/2025AerialPhotographyCached/ImageServer/tile/{z}/{y}/{x}",
        "preview_url_template": "https://www.fairfaxcounty.gov/gisimagery/rest/services/AerialPhotography/2025AerialPhotographyCached/ImageServer/tile/{z}/{y}/{x}",
        "attribution": "Fairfax County GIS",
        "default_center": {"lat": 38.8462, "lon": -77.3064, "zoom": 12},
        "default_min_zoom": 17,
        "default_max_zoom": 19,
        "note": "Best immediate default for Fairfax-area North Virginia testing.",
    },
    {
        "id": "loudoun_2023",
        "name": "Loudoun 2023 Ortho",
        "tile_url_template": "https://logis.loudoun.gov/image/rest/services/Aerial/COLOR_2023_CACHED/ImageServer/tile/{z}/{y}/{x}",
        "preview_url_template": "https://logis.loudoun.gov/image/rest/services/Aerial/COLOR_2023_CACHED/ImageServer/tile/{z}/{y}/{x}",
        "attribution": "Loudoun County LOGIS",
        "default_center": {"lat": 39.081, "lon": -77.55, "zoom": 11},
        "default_min_zoom": 17,
        "default_max_zoom": 19,
        "note": "Useful if your field box is in Loudoun County.",
    },
    {
        "id": "osm_placeholder",
        "name": "OSM Placeholder",
        "tile_url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "preview_url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "&copy; OpenStreetMap contributors",
        "default_center": {"lat": 38.89, "lon": -77.20, "zoom": 11},
        "default_min_zoom": 14,
        "default_max_zoom": 17,
        "note": "Only for UI bring-up. Do not use as the runtime imagery base.",
    },
]
DEFAULT_SOURCE_ID = "fairfax_2025"
DEFAULT_TILE_URL = next(
    item["tile_url_template"] for item in SOURCE_PRESETS if item["id"] == DEFAULT_SOURCE_ID
)
DEFAULT_USER_AGENT = "NatSecCelestScan-Dashboard/0.1"
MAX_TILE_DOWNLOAD = 5000
REQUEST_DELAY_S = 0.05
DEFAULT_EMBED_MODEL = "facebook/dinov3-vitl16-pretrain-sat493m"
DEFAULT_EMBED_DEVICE = "auto"
DEFAULT_EMBED_BATCH_SIZE = 4
DEFAULT_NMEA_LISTEN_HOST = os.getenv("NATSEC_DASH_NMEA_HOST", "0.0.0.0")
DEFAULT_NMEA_LISTEN_PORT = int(os.getenv("NATSEC_DASH_NMEA_PORT", "10110"))
DEFAULT_DEBUG_LISTEN_HOST = os.getenv("NATSEC_DASH_DEBUG_HOST", "0.0.0.0")
DEFAULT_DEBUG_LISTEN_PORT = int(os.getenv("NATSEC_DASH_DEBUG_PORT", "10111"))
DEFAULT_CAMERA_STREAM_PORT = int(os.getenv("NATSEC_DASH_CAMERA_PORT", "8080"))

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["JSON_SORT_KEYS"] = False

jobs_lock = threading.Lock()
jobs: dict[str, dict[str, object]] = {}
telemetry_lock = threading.Lock()
telemetry_runtime_lock = threading.Lock()
telemetry_runtime_started = False
telemetry_state: dict[str, object] = {
    "started": False,
    "nmea_listener": {
        "host": DEFAULT_NMEA_LISTEN_HOST,
        "port": DEFAULT_NMEA_LISTEN_PORT,
        "packets": 0,
        "last_received_at": 0.0,
        "source_ip": "",
        "error": "",
        "gga": "",
        "rmc": "",
    },
    "debug_listener": {
        "host": DEFAULT_DEBUG_LISTEN_HOST,
        "port": DEFAULT_DEBUG_LISTEN_PORT,
        "packets": 0,
        "last_received_at": 0.0,
        "source_ip": "",
        "error": "",
        "packet": None,
    },
    "pose": {},
}


@dataclass
class BoundingBox:
    north: float
    south: float
    east: float
    west: float


@dataclass
class CollectionMetadata:
    collection_id: str
    name: str
    bbox: BoundingBox
    min_zoom: int
    max_zoom: int
    tile_count: int
    tile_url_template: str
    created_at: float


def ensure_data_dirs() -> None:
    COLLECTIONS_ROOT.mkdir(parents=True, exist_ok=True)


def clamp_lat(lat: float) -> float:
    return max(-85.05112878, min(85.05112878, lat))


def normalize_bbox(payload: dict[str, object]) -> BoundingBox:
    north = float(payload["north"])
    south = float(payload["south"])
    east = float(payload["east"])
    west = float(payload["west"])
    if south > north:
        south, north = north, south
    if west > east:
        west, east = east, west
    return BoundingBox(
        north=clamp_lat(north),
        south=clamp_lat(south),
        east=max(-180.0, min(180.0, east)),
        west=max(-180.0, min(180.0, west)),
    )


def slugify_name(name: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "-" for char in name.strip())
    cleaned = "-".join(filter(None, cleaned.split("-")))
    return cleaned or "collection"


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    lat_rad = math.radians(clamp_lat(lat_deg))
    n = 2.0**zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    xtile = max(0, min(int(n) - 1, xtile))
    ytile = max(0, min(int(n) - 1, ytile))
    return xtile, ytile


def tile_ranges_for_bbox(bbox: BoundingBox, zoom: int) -> tuple[tuple[int, int], tuple[int, int]]:
    x1, y1 = deg2num(bbox.north, bbox.west, zoom)
    x2, y2 = deg2num(bbox.south, bbox.east, zoom)
    min_x, max_x = sorted((x1, x2))
    min_y, max_y = sorted((y1, y2))
    return (min_x, max_x), (min_y, max_y)


def iter_tiles_for_bbox(bbox: BoundingBox, min_zoom: int, max_zoom: int):
    for zoom in range(min_zoom, max_zoom + 1):
        (min_x, max_x), (min_y, max_y) = tile_ranges_for_bbox(bbox, zoom)
        for x in range(min_x, max_x + 1):
            for y in range(min_y, max_y + 1):
                yield zoom, x, y


def estimate_tile_count(bbox: BoundingBox, min_zoom: int, max_zoom: int) -> int:
    total = 0
    for zoom in range(min_zoom, max_zoom + 1):
        (min_x, max_x), (min_y, max_y) = tile_ranges_for_bbox(bbox, zoom)
        width = max(0, max_x - min_x + 1)
        height = max(0, max_y - min_y + 1)
        total += width * height
    return total


def collection_dir(collection_id: str) -> Path:
    return COLLECTIONS_ROOT / collection_id


def metadata_path(collection_id: str) -> Path:
    return collection_dir(collection_id) / "metadata.json"


def embeddings_dir(collection_id: str) -> Path:
    return collection_dir(collection_id) / "embeddings"


def embedding_manifest_path(collection_id: str) -> Path:
    return embeddings_dir(collection_id) / "manifest.json"


def load_collection_metadata(collection_id: str) -> CollectionMetadata | None:
    path = metadata_path(collection_id)
    if not path.exists():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return CollectionMetadata(
        collection_id=payload["collection_id"],
        name=payload["name"],
        bbox=BoundingBox(**payload["bbox"]),
        min_zoom=int(payload["min_zoom"]),
        max_zoom=int(payload["max_zoom"]),
        tile_count=int(payload["tile_count"]),
        tile_url_template=payload["tile_url_template"],
        created_at=float(payload["created_at"]),
    )


def save_collection_metadata(metadata: CollectionMetadata) -> None:
    target = metadata_path(metadata.collection_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(asdict(metadata), indent=2), encoding="utf-8")


def load_embedding_manifest(collection_id: str) -> dict[str, object] | None:
    path = embedding_manifest_path(collection_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def serialize_collection(metadata: CollectionMetadata) -> dict[str, object]:
    payload = asdict(metadata)
    manifest = load_embedding_manifest(metadata.collection_id)
    payload["has_embeddings"] = manifest is not None
    payload["embedding_manifest"] = manifest
    return payload


def list_collections() -> list[CollectionMetadata]:
    ensure_data_dirs()
    collections = []
    for path in COLLECTIONS_ROOT.iterdir():
        if not path.is_dir():
            continue
        metadata = load_collection_metadata(path.name)
        if metadata is not None:
            collections.append(metadata)
    collections.sort(key=lambda item: item.created_at, reverse=True)
    return collections


def tile_file_path(collection_id: str, zoom: int, x: int, y: int) -> Path:
    return collection_dir(collection_id) / "tiles" / str(zoom) / str(x) / f"{y}.png"


def update_job(job_id: str, **fields: object) -> None:
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id].update(fields)


def create_job(collection_id: str, name: str, total_items: int, job_type: str) -> str:
    job_id = uuid.uuid4().hex
    with jobs_lock:
        jobs[job_id] = {
            "job_id": job_id,
            "collection_id": collection_id,
            "name": name,
            "job_type": job_type,
            "status": "queued",
            "total_items": total_items,
            "completed_items": 0,
            "error": "",
            "detail": "",
            "started_at": time.time(),
            "finished_at": 0.0,
        }
    return job_id


def get_job(job_id: str) -> dict[str, object] | None:
    with jobs_lock:
        job = jobs.get(job_id)
        return None if job is None else dict(job)


def ensure_runtime_services_started() -> None:
    global telemetry_runtime_started
    with telemetry_runtime_lock:
        if telemetry_runtime_started:
            return
        start_listener_thread(run_nmea_listener, "dash-nmea-listener")
        start_listener_thread(run_debug_listener, "dash-debug-listener")
        telemetry_runtime_started = True
        with telemetry_lock:
            telemetry_state["started"] = True


def start_listener_thread(target, name: str) -> None:
    worker = threading.Thread(target=target, name=name, daemon=True)
    worker.start()


def run_nmea_listener() -> None:
    state_key = "nmea_listener"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((DEFAULT_NMEA_LISTEN_HOST, DEFAULT_NMEA_LISTEN_PORT))
    except OSError as exc:
        with telemetry_lock:
            telemetry_state[state_key]["error"] = str(exc)
        sock.close()
        return

    while True:
        try:
            data, addr = sock.recvfrom(8192)
            now = time.time()
            payload = data.decode("ascii", errors="ignore")
            for sentence in payload.replace("\r", "\n").split("\n"):
                sentence = sentence.strip()
                if not sentence:
                    continue
                parsed = parse_nmea_sentence(sentence)
                with telemetry_lock:
                    listener = telemetry_state[state_key]
                    listener["packets"] = int(listener["packets"]) + 1
                    listener["last_received_at"] = now
                    listener["source_ip"] = addr[0]
                    listener["error"] = ""
                    if parsed["type"] == "GGA":
                        listener["gga"] = sentence
                        merge_pose_update(parsed["fields"], source_ip=addr[0], received_at=now)
                    elif parsed["type"] == "RMC":
                        listener["rmc"] = sentence
                        merge_pose_update(parsed["fields"], source_ip=addr[0], received_at=now)
        except Exception as exc:  # pragma: no cover
            with telemetry_lock:
                telemetry_state[state_key]["error"] = str(exc)


def run_debug_listener() -> None:
    state_key = "debug_listener"
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((DEFAULT_DEBUG_LISTEN_HOST, DEFAULT_DEBUG_LISTEN_PORT))
    except OSError as exc:
        with telemetry_lock:
            telemetry_state[state_key]["error"] = str(exc)
        sock.close()
        return

    while True:
        try:
            data, addr = sock.recvfrom(65535)
            now = time.time()
            packet = json.loads(data.decode("utf-8", errors="ignore"))
            with telemetry_lock:
                listener = telemetry_state[state_key]
                listener["packets"] = int(listener["packets"]) + 1
                listener["last_received_at"] = now
                listener["source_ip"] = addr[0]
                listener["error"] = ""
                listener["packet"] = packet
                merge_debug_update(packet, source_ip=addr[0], received_at=now)
        except Exception as exc:  # pragma: no cover
            with telemetry_lock:
                telemetry_state[state_key]["error"] = str(exc)


def parse_nmea_sentence(sentence: str) -> dict[str, object]:
    if not sentence.startswith("$") or "*" not in sentence:
        return {"type": "UNKNOWN", "fields": {}}
    if not validate_checksum(sentence):
        return {"type": "UNKNOWN", "fields": {}}
    body = sentence[1:].split("*", 1)[0]
    fields = body.split(",")
    sentence_type = fields[0]
    if sentence_type == "GPGGA":
        return {
            "type": "GGA",
            "fields": {
                "lat": parse_nmea_coord(fields[2], fields[3]),
                "lon": parse_nmea_coord(fields[4], fields[5]),
                "fix_quality": parse_int(fields[6]),
                "satellites": parse_int(fields[7]),
                "hdop": parse_float(fields[8]),
                "alt_m": parse_float(fields[9]),
                "utc_time": fields[1],
            },
        }
    if sentence_type == "GPRMC":
        return {
            "type": "RMC",
            "fields": {
                "status": fields[2],
                "lat": parse_nmea_coord(fields[3], fields[4]),
                "lon": parse_nmea_coord(fields[5], fields[6]),
                "speed_knots": parse_float(fields[7]),
                "heading_deg": parse_float(fields[8]),
                "utc_time": fields[1],
                "utc_date": fields[9],
            },
        }
    return {"type": "UNKNOWN", "fields": {}}


def validate_checksum(sentence: str) -> bool:
    body, given = sentence[1:].split("*", 1)
    checksum = 0
    for char in body:
        checksum ^= ord(char)
    return f"{checksum:02X}" == given.strip().upper()


def parse_nmea_coord(value: str, hemisphere: str) -> float | None:
    if not value or not hemisphere:
        return None
    degree_digits = 2 if hemisphere in {"N", "S"} else 3
    if len(value) < degree_digits + 2:
        return None
    try:
        degrees = float(value[:degree_digits])
        minutes = float(value[degree_digits:])
    except ValueError:
        return None
    decimal = degrees + (minutes / 60.0)
    if hemisphere in {"S", "W"}:
        decimal = -decimal
    return decimal


def parse_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_int(value: str) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def merge_pose_update(fields: dict[str, object], *, source_ip: str, received_at: float) -> None:
    pose = dict(telemetry_state.get("pose") or {})
    if fields.get("lat") is not None:
        pose["lat"] = float(fields["lat"])
    if fields.get("lon") is not None:
        pose["lon"] = float(fields["lon"])
    if fields.get("alt_m") is not None:
        pose["alt_m"] = float(fields["alt_m"])
    if fields.get("heading_deg") is not None:
        pose["heading_deg"] = float(fields["heading_deg"])
    if fields.get("fix_quality") is not None:
        pose["fix_quality"] = int(fields["fix_quality"])
    if fields.get("satellites") is not None:
        pose["satellites"] = int(fields["satellites"])
    if fields.get("status"):
        pose["status"] = fields["status"]
    if fields.get("speed_knots") is not None:
        pose["speed_knots"] = float(fields["speed_knots"])
    pose["source_ip"] = source_ip
    pose["last_received_at"] = received_at
    telemetry_state["pose"] = pose


def merge_debug_update(packet: dict[str, object], *, source_ip: str, received_at: float) -> None:
    pose = dict(telemetry_state.get("pose") or {})
    packet_pose = packet.get("pose") or {}
    if isinstance(packet_pose, dict):
        for key in ("lat", "lon", "alt_m", "heading_deg", "confidence", "fix_type"):
            if packet_pose.get(key) is not None:
                pose[key] = packet_pose[key]
    pose["source_ip"] = source_ip
    pose["last_debug_at"] = received_at
    telemetry_state["pose"] = pose


def get_telemetry_snapshot() -> dict[str, object]:
    with telemetry_lock:
        pose = dict(telemetry_state.get("pose") or {})
        nmea_listener = dict(telemetry_state["nmea_listener"])
        debug_listener = dict(telemetry_state["debug_listener"])
        debug_packet = debug_listener.get("packet")
        source_ip = ""
        if isinstance(debug_packet, dict):
            source_ip = str(debug_listener.get("source_ip") or "")
        if not source_ip:
            source_ip = str(nmea_listener.get("source_ip") or "")
        camera_base = f"http://{source_ip}:{DEFAULT_CAMERA_STREAM_PORT}" if source_ip else ""
        return {
            "started": telemetry_state["started"],
            "listeners": {
                "nmea": {
                    "host": nmea_listener["host"],
                    "port": nmea_listener["port"],
                    "packets": nmea_listener["packets"],
                    "last_received_at": nmea_listener["last_received_at"],
                    "source_ip": nmea_listener["source_ip"],
                    "error": nmea_listener["error"],
                    "gga": nmea_listener["gga"],
                    "rmc": nmea_listener["rmc"],
                },
                "debug": {
                    "host": debug_listener["host"],
                    "port": debug_listener["port"],
                    "packets": debug_listener["packets"],
                    "last_received_at": debug_listener["last_received_at"],
                    "source_ip": debug_listener["source_ip"],
                    "error": debug_listener["error"],
                },
            },
            "pose": pose,
            "debug": debug_packet if isinstance(debug_packet, dict) else None,
            "camera": {
                "source_ip": source_ip,
                "port": DEFAULT_CAMERA_STREAM_PORT,
                "base_url": camera_base,
                "cam0_url": f"{camera_base}/stream/cam0" if camera_base else "",
                "cam1_url": f"{camera_base}/stream/cam1" if camera_base else "",
                "health_url": f"{camera_base}/health" if camera_base else "",
            },
            "server_time": time.time(),
        }


def download_collection(job_id: str, metadata: CollectionMetadata) -> None:
    update_job(job_id, status="running")
    session = requests.Session()
    session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
    downloaded = 0
    try:
        for zoom, x, y in iter_tiles_for_bbox(metadata.bbox, metadata.min_zoom, metadata.max_zoom):
            target = tile_file_path(metadata.collection_id, zoom, x, y)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                downloaded += 1
                update_job(job_id, completed_items=downloaded, detail=f"cached z={zoom} x={x} y={y}")
                continue
            url = metadata.tile_url_template.format(z=zoom, x=x, y=y)
            response = session.get(url, timeout=20)
            response.raise_for_status()
            target.write_bytes(response.content)
            downloaded += 1
            update_job(job_id, completed_items=downloaded, detail=f"downloaded z={zoom} x={x} y={y}")
            time.sleep(REQUEST_DELAY_S)
    except Exception as exc:
        update_job(job_id, status="failed", error=str(exc), finished_at=time.time())
        return

    save_collection_metadata(metadata)
    update_job(job_id, status="completed", completed_items=downloaded, finished_at=time.time(), detail="tile download complete")


def run_embedding_job(
    job_id: str,
    collection_id: str,
    model_name: str,
    device: str,
    batch_size: int,
    overwrite: bool,
    limit: int,
) -> None:
    update_job(job_id, status="running", detail=f"starting {model_name}")
    command = [
        sys.executable,
        "-u",
        str(EMBED_SCRIPT),
        collection_id,
        "--model-name",
        model_name,
        "--device",
        device,
        "--batch-size",
        str(batch_size),
    ]
    if overwrite:
        command.append("--overwrite")
    if limit > 0:
        command.extend(["--limit", str(limit)])

    process = subprocess.Popen(
        command,
        cwd=str(APP_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    completed_items = 0
    output_lines: list[str] = []
    try:
        assert process.stdout is not None
        for line in process.stdout:
            current_line = line.strip()
            if current_line:
                output_lines.append(current_line)
            match = re.search(r"embedded (\d+) tiles", current_line)
            if match:
                completed_items += int(match.group(1))
            if current_line:
                update_job(job_id, completed_items=completed_items, detail=current_line)
    finally:
        remainder = ""
        if process.stdout is not None:
            remainder = process.stdout.read()
        return_code = process.wait()

    if remainder:
        for raw_line in remainder.splitlines():
            current_line = raw_line.strip()
            if not current_line:
                continue
            output_lines.append(current_line)
            match = re.search(r"embedded (\d+) tiles", current_line)
            if match:
                completed_items += int(match.group(1))
            update_job(job_id, completed_items=completed_items, detail=current_line)

    last_line = output_lines[-1] if output_lines else ""
    if return_code != 0:
        update_job(
            job_id,
            status="failed",
            error=last_line or f"embed script exited with code {return_code}",
            finished_at=time.time(),
        )
        return

    manifest = load_embedding_manifest(collection_id)
    final_count = completed_items
    if manifest is not None:
        final_count = int(manifest.get("tile_count", completed_items))
    update_job(
        job_id,
        status="completed",
        completed_items=final_count,
        finished_at=time.time(),
        detail="embedding index complete",
    )


@app.get("/")
def index():
    ensure_runtime_services_started()
    return render_template("index.html")


@app.get("/api/config")
def api_config():
    ensure_runtime_services_started()
    default_source = next(item for item in SOURCE_PRESETS if item["id"] == DEFAULT_SOURCE_ID)
    return jsonify(
        {
            "default_tile_url": DEFAULT_TILE_URL,
            "default_source_id": DEFAULT_SOURCE_ID,
            "source_presets": SOURCE_PRESETS,
            "default_center": default_source["default_center"],
            "max_tile_download": MAX_TILE_DOWNLOAD,
            "default_embed_model": DEFAULT_EMBED_MODEL,
            "default_embed_device": DEFAULT_EMBED_DEVICE,
            "default_embed_batch_size": DEFAULT_EMBED_BATCH_SIZE,
            "telemetry": {
                "nmea_listen_host": DEFAULT_NMEA_LISTEN_HOST,
                "nmea_listen_port": DEFAULT_NMEA_LISTEN_PORT,
                "debug_listen_host": DEFAULT_DEBUG_LISTEN_HOST,
                "debug_listen_port": DEFAULT_DEBUG_LISTEN_PORT,
                "camera_stream_port": DEFAULT_CAMERA_STREAM_PORT,
            },
        }
    )


@app.get("/api/telemetry/latest")
def api_telemetry_latest():
    ensure_runtime_services_started()
    return jsonify(get_telemetry_snapshot())


@app.get("/api/collections")
def api_collections():
    payload = [serialize_collection(item) for item in list_collections()]
    return jsonify(payload)


@app.get("/api/collections/<collection_id>")
def api_collection_detail(collection_id: str):
    metadata = load_collection_metadata(collection_id)
    if metadata is None:
        abort(404)
    return jsonify(serialize_collection(metadata))


@app.post("/api/estimate")
def api_estimate():
    payload = request.get_json(force=True)
    bbox = normalize_bbox(payload["bbox"])
    min_zoom = int(payload["min_zoom"])
    max_zoom = int(payload["max_zoom"])
    if min_zoom > max_zoom:
        min_zoom, max_zoom = max_zoom, min_zoom
    tile_count = estimate_tile_count(bbox, min_zoom, max_zoom)
    return jsonify({"tile_count": tile_count})


@app.post("/api/downloads")
def api_download():
    payload = request.get_json(force=True)
    bbox = normalize_bbox(payload["bbox"])
    min_zoom = int(payload["min_zoom"])
    max_zoom = int(payload["max_zoom"])
    if min_zoom > max_zoom:
        min_zoom, max_zoom = max_zoom, min_zoom
    tile_count = estimate_tile_count(bbox, min_zoom, max_zoom)
    if tile_count > MAX_TILE_DOWNLOAD:
        return jsonify({"error": f"selection too large: {tile_count} tiles exceeds limit of {MAX_TILE_DOWNLOAD}"}), 400

    requested_name = str(payload.get("name") or "").strip()
    base_name = slugify_name(requested_name or f"tiles-{time.strftime('%Y%m%d-%H%M%S')}")
    collection_id = f"{base_name}-{uuid.uuid4().hex[:8]}"
    metadata = CollectionMetadata(
        collection_id=collection_id,
        name=requested_name or collection_id,
        bbox=bbox,
        min_zoom=min_zoom,
        max_zoom=max_zoom,
        tile_count=tile_count,
        tile_url_template=str(payload.get("tile_url_template") or DEFAULT_TILE_URL).strip(),
        created_at=time.time(),
    )

    save_collection_metadata(metadata)
    job_id = create_job(collection_id, metadata.name, tile_count, "download")
    worker = threading.Thread(target=download_collection, args=(job_id, metadata), daemon=True)
    worker.start()
    return jsonify({"job_id": job_id, "collection_id": collection_id})


@app.post("/api/collections/<collection_id>/embed")
def api_embed_collection(collection_id: str):
    metadata = load_collection_metadata(collection_id)
    if metadata is None:
        abort(404)

    payload = request.get_json(silent=True) or {}
    model_name = str(payload.get("model_name") or DEFAULT_EMBED_MODEL).strip()
    device = str(payload.get("device") or DEFAULT_EMBED_DEVICE).strip()
    batch_size = max(1, int(payload.get("batch_size") or DEFAULT_EMBED_BATCH_SIZE))
    overwrite = bool(payload.get("overwrite"))
    limit = max(0, int(payload.get("limit") or 0))
    total_items = min(metadata.tile_count, limit) if limit > 0 else metadata.tile_count

    job_id = create_job(collection_id, metadata.name, total_items, "embed")
    worker = threading.Thread(
        target=run_embedding_job,
        args=(job_id, collection_id, model_name, device, batch_size, overwrite, limit),
        daemon=True,
    )
    worker.start()
    return jsonify({"job_id": job_id, "collection_id": collection_id})


@app.get("/api/jobs/<job_id>")
def api_job(job_id: str):
    job = get_job(job_id)
    if job is None:
        abort(404)
    return jsonify(job)


@app.get("/tiles/<collection_id>/<int:zoom>/<int:x>/<int:y>.png")
def serve_cached_tile(collection_id: str, zoom: int, x: int, y: int):
    path = tile_file_path(collection_id, zoom, x, y)
    if not path.exists():
        abort(404)
    return send_file(path, mimetype="image/png")


if __name__ == "__main__":
    ensure_data_dirs()
    ensure_runtime_services_started()
    app.run(host="0.0.0.0", port=5000, debug=True, use_reloader=False)
