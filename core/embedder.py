import os
import numpy as np
from config import EMBEDDING_MODEL

# 4 threads — good balance for Apple Silicon with 18GB RAM
os.environ.setdefault("OMP_NUM_THREADS", "4")
os.environ.setdefault("MKL_NUM_THREADS", "4")

import torch
torch.set_num_threads(4)

# batch_size for bulk indexing vs single queries
BULK_BATCH_SIZE = 128


class Embedder:
    _model = None

    def _load(self):
        if Embedder._model is None:
            import logging
            import warnings
            from sentence_transformers import SentenceTransformer
            # Suppress "position_ids UNEXPECTED" warning from e5-base model load
            logging.getLogger("sentence_transformers").setLevel(logging.ERROR)
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                Embedder._model = SentenceTransformer(EMBEDDING_MODEL)
            logging.getLogger("sentence_transformers").setLevel(logging.WARNING)
            Embedder._model.max_seq_length = 256  # truncate long messages

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query. Uses 'query: ' prefix per e5 spec."""
        self._load()
        return Embedder._model.encode(
            f"query: {text}", normalize_embeddings=True
        ).astype(np.float32)

    def embed_passages(self, texts: list[str], batch_size: int = BULK_BATCH_SIZE) -> np.ndarray:
        """Embed document passages. Uses 'passage: ' prefix per e5 spec."""
        self._load()
        return Embedder._model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True, batch_size=batch_size,
        ).astype(np.float32)
