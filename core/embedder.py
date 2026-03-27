# core/embedder.py
"""Embedder facade — uses ONNX if available, falls back to PyTorch.

ONNX: import ~0.1s, inference ~14ms (requires scripts/export_onnx.py first).
PyTorch: import ~2.4s, inference ~45ms (original, always available).
"""
import numpy as np
from config import ONNX_MODEL_PATH


def _get_backend():
    """Return best available embedder backend."""
    if ONNX_MODEL_PATH.exists():
        try:
            from core.embedder_onnx import OnnxEmbedder
            return OnnxEmbedder()
        except ImportError:
            pass
    # Fallback to PyTorch
    from core.embedder_pytorch import PyTorchEmbedder
    return PyTorchEmbedder()


class Embedder:
    _backend = None

    def _load(self):
        if Embedder._backend is None:
            Embedder._backend = _get_backend()

    def embed_query(self, text: str) -> np.ndarray:
        self._load()
        return Embedder._backend.embed_query(text)

    def embed_passages(self, texts: list[str], batch_size: int = 128) -> np.ndarray:
        self._load()
        return Embedder._backend.embed_passages(texts, batch_size=batch_size)
