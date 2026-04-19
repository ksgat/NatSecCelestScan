from __future__ import annotations

from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover
    np = None

try:
    import torch
    import torch.nn.functional as torch_f
except ImportError:  # pragma: no cover
    torch = None
    torch_f = None

try:
    from transformers import AutoImageProcessor, AutoModel
except ImportError:  # pragma: no cover
    AutoImageProcessor = None
    AutoModel = None


@dataclass
class EmbeddingBackendStatus:
    available: bool
    model_name: str
    device: str
    last_error: str = ""


class EmbeddingBackend:
    def status(self) -> EmbeddingBackendStatus:
        raise NotImplementedError

    def embed_frame(self, frame):
        raise NotImplementedError


class DisabledEmbeddingBackend(EmbeddingBackend):
    def status(self) -> EmbeddingBackendStatus:
        return EmbeddingBackendStatus(
            available=False,
            model_name="disabled",
            device="disabled",
            last_error="runtime embeddings disabled",
        )

    def embed_frame(self, frame):
        return None


class HuggingFaceEmbeddingBackend(EmbeddingBackend):
    def __init__(self, model_name: str, device: str = "auto") -> None:
        self._model_name = model_name
        self._requested_device = device
        self._resolved_device = self._resolve_device(device)
        self._processor = None
        self._model = None
        self._last_error = ""

    def status(self) -> EmbeddingBackendStatus:
        available = np is not None and torch is not None and AutoImageProcessor is not None and AutoModel is not None
        return EmbeddingBackendStatus(
            available=available,
            model_name=self._model_name,
            device=self._resolved_device,
            last_error=self._last_error,
        )

    def embed_frame(self, frame):
        if frame is None or np is None:
            return None
        status = self.status()
        if not status.available:
            self._last_error = "transformers/torch/numpy backend unavailable"
            return None
        try:
            self._lazy_load()
            array = np.asarray(frame)
            if array.ndim == 2:
                array = np.repeat(array[..., None], 3, axis=2)
            elif array.ndim == 3 and array.shape[2] == 4:
                array = array[..., :3]
            if array.ndim == 3 and array.shape[2] == 3:
                array = array[..., ::-1]
            inputs = self._processor(images=array, return_tensors="pt")
            inputs = {key: value.to(self._resolved_device) for key, value in inputs.items()}
            with torch.inference_mode():
                outputs = self._model(**inputs)
            pooled = getattr(outputs, "pooler_output", None)
            if pooled is None:
                hidden = getattr(outputs, "last_hidden_state", None)
                if hidden is None:
                    raise RuntimeError("model output has no pooler_output or last_hidden_state")
                pooled = hidden.mean(dim=1)
            normalized = torch_f.normalize(pooled, p=2, dim=-1)
            return normalized[0].detach().cpu().numpy().astype("float32")
        except Exception as exc:  # pragma: no cover
            self._last_error = str(exc)
            return None

    def _lazy_load(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        self._processor = AutoImageProcessor.from_pretrained(self._model_name)
        self._model = AutoModel.from_pretrained(self._model_name)
        self._model.eval()
        self._model.to(self._resolved_device)

    @staticmethod
    def _resolve_device(device: str) -> str:
        if device != "auto":
            return device
        if torch is not None and torch.cuda.is_available():
            return "cuda"
        return "cpu"


def build_embedding_backend(model_name: str, device: str = "auto", enabled: bool = True) -> EmbeddingBackend:
    if not enabled:
        return DisabledEmbeddingBackend()
    return HuggingFaceEmbeddingBackend(model_name=model_name, device=device)
