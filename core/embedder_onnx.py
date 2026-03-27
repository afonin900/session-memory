"""ONNX Runtime embedder — replaces PyTorch sentence_transformers.

Import time: ~0.1s (vs 2.4s for sentence_transformers).
Inference: ~14ms per query (vs 45ms PyTorch).

Requires: pip install onnxruntime tokenizers numpy
Model: run scripts/export_onnx.py first.

Model inputs:  input_ids, attention_mask  (no token_type_ids)
Model outputs: token_embeddings (batch, seq, 768), sentence_embedding (batch, 768)
               sentence_embedding is already mean-pooled and L2-normalized.
"""
import numpy as np
from config import ONNX_MODEL_PATH, ONNX_TOKENIZER_NAME

BULK_BATCH_SIZE = 128


class OnnxEmbedder:
    _session = None
    _tokenizer = None

    def _load(self):
        if OnnxEmbedder._session is None:
            import onnxruntime as ort
            from tokenizers import Tokenizer

            if not ONNX_MODEL_PATH.exists():
                raise FileNotFoundError(
                    f"ONNX model not found at {ONNX_MODEL_PATH}. "
                    "Run: python3 scripts/export_onnx.py"
                )

            OnnxEmbedder._session = ort.InferenceSession(
                str(ONNX_MODEL_PATH),
                providers=["CPUExecutionProvider"],
            )
            OnnxEmbedder._tokenizer = Tokenizer.from_pretrained(ONNX_TOKENIZER_NAME)
            OnnxEmbedder._tokenizer.enable_truncation(max_length=256)
            OnnxEmbedder._tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")

    def _encode(self, texts: list[str]) -> np.ndarray:
        """Encode texts to normalized embeddings.

        Uses the model's sentence_embedding output which is already
        mean-pooled and L2-normalized — no post-processing needed.
        """
        self._load()
        encodings = OnnxEmbedder._tokenizer.encode_batch(texts)

        input_ids = np.array([e.ids for e in encodings], dtype=np.int64)
        attention_mask = np.array([e.attention_mask for e in encodings], dtype=np.int64)

        # Model has no token_type_ids input — only input_ids and attention_mask
        outputs = OnnxEmbedder._session.run(
            None,
            {
                "input_ids": input_ids,
                "attention_mask": attention_mask,
            },
        )

        # outputs[1] = sentence_embedding: (batch, 768), already pooled + L2-normalized
        return outputs[1].astype(np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        """Embed a search query. Uses 'query: ' prefix per e5 spec."""
        return self._encode([f"query: {text}"])[0]

    def embed_passages(self, texts: list[str], batch_size: int = BULK_BATCH_SIZE) -> np.ndarray:
        """Embed document passages. Uses 'passage: ' prefix per e5 spec."""
        prefixed = [f"passage: {t}" for t in texts]

        if len(prefixed) <= batch_size:
            return self._encode(prefixed)

        all_embeddings = []
        for i in range(0, len(prefixed), batch_size):
            batch = prefixed[i:i + batch_size]
            all_embeddings.append(self._encode(batch))
        return np.vstack(all_embeddings)
