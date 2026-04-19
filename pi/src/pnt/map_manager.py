from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

from .config import MapCollectionConfig, MissionBounds
from .models import MapTileCandidate


@dataclass
class LoadedCollection:
    collection_id: str
    root: Path
    tile_root: Path
    metadata: dict[str, object]
    tiles: list[dict[str, object]]
    manifest: dict[str, object] | None = None
    vectors: object | None = None


class MapManager:
    def __init__(self, root: Path, bounds: MissionBounds, config: MapCollectionConfig | None = None) -> None:
        self._root = root
        self._bounds = bounds
        self._config = config or MapCollectionConfig()
        self._collection = self._load_collection()

    def query_candidate_tiles(self, lat: float, lon: float, query_embedding=None, top_k: int | None = None) -> list[MapTileCandidate]:
        if self._collection is None:
            return []

        candidates = self._build_spatial_candidates(lat, lon)
        if not candidates:
            return []

        limit = max(1, top_k or self._config.candidate_search_limit)
        if query_embedding is not None and self.has_embeddings():
            ranked = self._rank_with_embeddings(candidates, query_embedding)
            return ranked[:limit]

        candidates.sort(key=lambda candidate: candidate.distance_m)
        return candidates[:limit]

    def has_embeddings(self) -> bool:
        return self._collection is not None and self._collection.vectors is not None

    @property
    def bounds(self) -> MissionBounds:
        return self._bounds

    @property
    def active_collection_id(self) -> str | None:
        return None if self._collection is None else self._collection.collection_id

    def _build_spatial_candidates(self, lat: float, lon: float) -> list[MapTileCandidate]:
        assert self._collection is not None
        radius_m = self._config.seed_search_radius_m
        candidates: list[MapTileCandidate] = []
        for tile in self._collection.tiles:
            zoom = int(tile["zoom"])
            x = int(tile["x"])
            y = int(tile["y"])
            north, south, west, east = tile_bounds(zoom, x, y)
            lat_center = (north + south) / 2.0
            lon_center = (east + west) / 2.0
            distance_m = haversine_m(lat, lon, lat_center, lon_center)
            if distance_m > radius_m:
                continue
            candidates.append(
                MapTileCandidate(
                    collection_id=self._collection.collection_id,
                    path=self._collection.tile_root / str(tile["rel_path"]),
                    zoom=zoom,
                    x=x,
                    y=y,
                    north=north,
                    south=south,
                    east=east,
                    west=west,
                    lat_center=lat_center,
                    lon_center=lon_center,
                    meters_per_pixel=tile_meters_per_pixel(zoom, lat_center),
                    embedding_score=0.0,
                    distance_m=distance_m,
                    source=str(self._collection.metadata.get("tile_url_template", "cached")),
                )
            )
        return candidates

    def _rank_with_embeddings(self, candidates: list[MapTileCandidate], query_embedding) -> list[MapTileCandidate]:
        assert self._collection is not None and self._collection.vectors is not None and np is not None
        vectors = np.asarray(self._collection.vectors)
        query = np.asarray(query_embedding, dtype="float32").reshape(-1)
        norm = float(np.linalg.norm(query))
        if norm <= 1e-9:
            candidates.sort(key=lambda candidate: candidate.distance_m)
            return candidates
        query = query / norm

        tile_lookup = {(int(tile["zoom"]), int(tile["x"]), int(tile["y"])): index for index, tile in enumerate(self._collection.tiles)}
        ranked: list[MapTileCandidate] = []
        for candidate in candidates:
            index = tile_lookup.get((candidate.zoom, candidate.x, candidate.y))
            if index is None:
                continue
            score = float(vectors[index] @ query)
            ranked.append(
                MapTileCandidate(
                    collection_id=candidate.collection_id,
                    path=candidate.path,
                    zoom=candidate.zoom,
                    x=candidate.x,
                    y=candidate.y,
                    north=candidate.north,
                    south=candidate.south,
                    east=candidate.east,
                    west=candidate.west,
                    lat_center=candidate.lat_center,
                    lon_center=candidate.lon_center,
                    meters_per_pixel=candidate.meters_per_pixel,
                    embedding_score=score,
                    distance_m=candidate.distance_m,
                    source=candidate.source,
                )
            )
        ranked.sort(key=lambda candidate: (-candidate.embedding_score, candidate.distance_m))
        return ranked

    def _load_collection(self) -> LoadedCollection | None:
        collection_root = self._resolve_collection_root()
        if collection_root is None:
            return None

        metadata_path = collection_root / "metadata.json"
        tile_root = collection_root / "tiles"
        if not metadata_path.exists() or not tile_root.exists():
            return None

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        tiles = self._load_tiles(collection_root)
        if not tiles:
            return None

        manifest = None
        vectors = None
        if np is not None:
            manifest_path = collection_root / "embeddings" / "manifest.json"
            vectors_path = collection_root / "embeddings" / "vectors.npy"
            if manifest_path.exists() and vectors_path.exists():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                vectors = np.load(vectors_path, mmap_mode="r")

        return LoadedCollection(
            collection_id=collection_root.name,
            root=collection_root,
            tile_root=tile_root,
            metadata=metadata,
            tiles=tiles,
            manifest=manifest,
            vectors=vectors,
        )

    def _load_tiles(self, collection_root: Path) -> list[dict[str, object]]:
        tiles_json = collection_root / "embeddings" / "tiles.json"
        if tiles_json.exists():
            tiles = json.loads(tiles_json.read_text(encoding="utf-8"))
            if tiles:
                return tiles

        tiles: list[dict[str, object]] = []
        for path in sorted((collection_root / "tiles").rglob("*.png")):
            rel = path.relative_to(collection_root / "tiles")
            if len(rel.parts) != 3:
                continue
            zoom, x, filename = rel.parts
            y = Path(filename).stem
            tiles.append(
                {
                    "zoom": int(zoom),
                    "x": int(x),
                    "y": int(y),
                    "rel_path": rel.as_posix(),
                }
            )
        return tiles

    def _resolve_collection_root(self) -> Path | None:
        root = self._config.collections_root
        if not root.exists():
            return None
        if self._config.active_collection_id:
            candidate = root / self._config.active_collection_id
            return candidate if candidate.exists() else None

        candidates = []
        for path in root.iterdir():
            if path.is_dir() and (path / "metadata.json").exists() and (path / "tiles").exists():
                candidates.append(path)
        if not candidates:
            return None
        candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        return candidates[0]


def tile_bounds(zoom: int, x: int, y: int) -> tuple[float, float, float, float]:
    north, west = num2deg(x, y, zoom)
    south, east = num2deg(x + 1, y + 1, zoom)
    return north, south, west, east


def num2deg(x: int, y: int, zoom: int) -> tuple[float, float]:
    n = 2.0**zoom
    lon_deg = x / n * 360.0 - 180.0
    lat_rad = math.atan(math.sinh(math.pi * (1.0 - 2.0 * y / n)))
    lat_deg = math.degrees(lat_rad)
    return lat_deg, lon_deg


def tile_meters_per_pixel(zoom: int, latitude_deg: float) -> float:
    return 156543.03392 * math.cos(math.radians(latitude_deg)) / (2**zoom)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    return 2.0 * radius_m * math.atan2(math.sqrt(a), math.sqrt(max(1e-12, 1.0 - a)))
