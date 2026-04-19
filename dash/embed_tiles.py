from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable


APP_ROOT = Path(__file__).resolve().parent
COLLECTIONS_ROOT = APP_ROOT / "data" / "collections"
DEFAULT_MODEL = "facebook/dinov3-vitl16-pretrain-sat493m"
DEFAULT_BATCH_SIZE = 4
DEFAULT_DEVICE = "auto"

try:
    import numpy as np
except ImportError as exc:  # pragma: no cover
    raise SystemExit("numpy is required for tile embedding generation") from exc

try:
    import torch
    import torch.nn.functional as F
except ImportError as exc:  # pragma: no cover
    raise SystemExit("torch is required for tile embedding generation") from exc

try:
    from PIL import Image
except ImportError as exc:  # pragma: no cover
    raise SystemExit("Pillow is required for tile embedding generation") from exc

try:
    from transformers import AutoImageProcessor, AutoModel
except ImportError as exc:  # pragma: no cover
    raise SystemExit("transformers is required for tile embedding generation") from exc


@dataclass(frozen=True)
class TileRecord:
    zoom: int
    x: int
    y: int
    rel_path: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DINOv3 embeddings for a cached tile collection.")
    parser.add_argument("collection_id", help="Collection id under dash/data/collections")
    parser.add_argument(
        "--model-name",
        default=DEFAULT_MODEL,
        help="Hugging Face model id. Default is the SAT-493M ViT-L backbone.",
    )
    parser.add_argument(
        "--device",
        default=DEFAULT_DEVICE,
        help="Torch device to run on: auto, cpu, or cuda",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help="Batch size for embedding generation",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional tile limit for smoke tests",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite an existing embedding index",
    )
    return parser.parse_args()


def collection_dir(collection_id: str) -> Path:
    return COLLECTIONS_ROOT / collection_id


def tiles_root(collection_id: str) -> Path:
    return collection_dir(collection_id) / "tiles"


def embeddings_root(collection_id: str) -> Path:
    return collection_dir(collection_id) / "embeddings"


def ensure_collection_exists(collection_id: str) -> None:
    root = tiles_root(collection_id)
    if not root.exists():
        raise SystemExit(f"tile collection not found: {root}")


def discover_tiles(collection_id: str, limit: int = 0) -> list[TileRecord]:
    root = tiles_root(collection_id)
    records: list[TileRecord] = []
    for path in sorted(root.rglob("*.png")):
        rel = path.relative_to(root)
        if len(rel.parts) != 3:
            continue
        zoom, x, filename = rel.parts
        y = Path(filename).stem
        records.append(TileRecord(int(zoom), int(x), int(y), rel.as_posix()))
        if limit > 0 and len(records) >= limit:
            break
    if not records:
        raise SystemExit(f"no PNG tiles found under {root}")
    return records


def batched(items: list[TileRecord], batch_size: int) -> Iterable[list[TileRecord]]:
    for start in range(0, len(items), batch_size):
        yield items[start : start + batch_size]


def load_model(model_name: str, device: str):
    processor = AutoImageProcessor.from_pretrained(model_name)
    model = AutoModel.from_pretrained(model_name)
    model.eval()
    model.to(device)
    return processor, model


def resolve_device(device: str) -> str:
    if device == "auto":
        return "cuda" if torch.cuda.is_available() else "cpu"
    return device


def load_images(collection_id: str, batch: list[TileRecord]) -> list[Image.Image]:
    root = tiles_root(collection_id)
    images: list[Image.Image] = []
    for tile in batch:
        path = root / tile.rel_path
        with Image.open(path) as image:
            images.append(image.convert("RGB"))
    return images


def extract_embedding(outputs) -> torch.Tensor:
    pooled = getattr(outputs, "pooler_output", None)
    if pooled is not None:
        return pooled
    hidden = getattr(outputs, "last_hidden_state", None)
    if hidden is None:
        raise RuntimeError("model output does not expose pooler_output or last_hidden_state")
    return hidden.mean(dim=1)


def generate_embeddings(collection_id: str, model_name: str, device: str, batch_size: int, limit: int = 0) -> dict[str, object]:
    tiles = discover_tiles(collection_id, limit=limit)
    resolved_device = resolve_device(device)
    processor, model = load_model(model_name, device=resolved_device)
    vectors: list[np.ndarray] = []
    started = time.time()

    for index, batch in enumerate(batched(tiles, batch_size), start=1):
        images = load_images(collection_id, batch)
        inputs = processor(images=images, return_tensors="pt")
        inputs = {key: value.to(resolved_device) for key, value in inputs.items()}
        with torch.inference_mode():
            outputs = model(**inputs)
        pooled = extract_embedding(outputs)
        pooled = F.normalize(pooled, p=2, dim=-1)
        vectors.append(pooled.detach().cpu().numpy().astype(np.float32))
        print(f"[{index}/{(len(tiles) + batch_size - 1) // batch_size}] embedded {len(batch)} tiles")

    matrix = np.concatenate(vectors, axis=0)
    elapsed = time.time() - started
    return {
        "tiles": tiles,
        "embeddings": matrix,
        "model_name": model_name,
        "device": resolved_device,
        "elapsed_s": elapsed,
    }


def save_index(collection_id: str, payload: dict[str, object], overwrite: bool) -> None:
    target_root = embeddings_root(collection_id)
    if target_root.exists() and not overwrite:
        raise SystemExit(f"embedding index already exists: {target_root} (use --overwrite)")
    target_root.mkdir(parents=True, exist_ok=True)

    vectors = payload["embeddings"]
    tiles: list[TileRecord] = payload["tiles"]
    np.save(target_root / "vectors.npy", vectors)
    (target_root / "tiles.json").write_text(
        json.dumps([asdict(tile) for tile in tiles], indent=2),
        encoding="utf-8",
    )
    manifest = {
        "collection_id": collection_id,
        "model_name": payload["model_name"],
        "device": payload["device"],
        "embedding_dim": int(vectors.shape[1]),
        "tile_count": int(vectors.shape[0]),
        "normalized": True,
        "created_at": time.time(),
        "elapsed_s": payload["elapsed_s"],
    }
    (target_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    ensure_collection_exists(args.collection_id)
    payload = generate_embeddings(
        collection_id=args.collection_id,
        model_name=args.model_name,
        device=args.device,
        batch_size=max(1, args.batch_size),
        limit=max(0, args.limit),
    )
    save_index(args.collection_id, payload, overwrite=args.overwrite)
    print(
        f"saved {payload['embeddings'].shape[0]} embeddings "
        f"({payload['embeddings'].shape[1]} dims) to {embeddings_root(args.collection_id)}"
    )


if __name__ == "__main__":
    main()
