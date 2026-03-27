# core/embedder_pytorch.py
"""PyTorch/sentence-transformers embedder — fallback when ONNX model not available."""
import numpy as np
from config import EMBEDDING_MODEL

BULK_BATCH_SIZE = 128


class PyTorchEmbedder:
    _model = None

    def _load(self):
        if PyTorchEmbedder._model is None:
            import os
            os.environ.setdefault("OMP_NUM_THREADS", "4")
            os.environ.setdefault("MKL_NUM_THREADS", "4")
            import torch
            torch.set_num_threads(4)
            import logging
            import warnings
            from sentence_transformers import SentenceTransformer
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                PyTorchEmbedder._model = SentenceTransformer(EMBEDDING_MODEL)
            logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
            PyTorchEmbedder._model.max_seq_length = 256

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query. Uses 'query: ' prefix per e5 spec."""
        self._load()
        return PyTorchEmbedder._model.encode(
            f"query: {text}", normalize_embeddings=True
        ).astype(np.float32)

    def embed_passages(self, texts: list[str], batch_size: int = BULK_BATCH_SIZE) -> np.ndarray:
        """Embed document passages. Uses 'passage: ' prefix per e5 spec."""
        self._load()
        return PyTorchEmbedder._model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True, batch_size=batch_size,
        ).astype(np.float32)
