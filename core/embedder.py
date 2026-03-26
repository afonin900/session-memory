import numpy as np
from config import EMBEDDING_MODEL


class Embedder:
    _model = None

    def _load(self):
        if Embedder._model is None:
            from sentence_transformers import SentenceTransformer
            Embedder._model = SentenceTransformer(EMBEDDING_MODEL)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query. Uses 'query: ' prefix per e5 spec."""
        self._load()
        return Embedder._model.encode(
            f"query: {text}", normalize_embeddings=True
        ).astype(np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        """Embed document passages. Uses 'passage: ' prefix per e5 spec."""
        self._load()
        return Embedder._model.encode(
            [f"passage: {t}" for t in texts],
            normalize_embeddings=True, batch_size=64,
        ).astype(np.float32)
