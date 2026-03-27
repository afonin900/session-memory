import pytest
import numpy as np
from config import ONNX_MODEL_PATH

pytestmark = pytest.mark.skipif(
    not ONNX_MODEL_PATH.exists(),
    reason="ONNX model not exported yet — run scripts/export_onnx.py first",
)


def test_onnx_embed_query():
    from core.embedder_onnx import OnnxEmbedder
    emb = OnnxEmbedder()
    vec = emb.embed_query("тест поиска по сессиям")
    assert vec.shape == (768,)
    assert vec.dtype == np.float32
    assert np.abs(np.linalg.norm(vec) - 1.0) < 0.01  # normalized


def test_onnx_embed_passages_batch():
    from core.embedder_onnx import OnnxEmbedder
    emb = OnnxEmbedder()
    texts = ["passage one", "passage two", "passage three"]
    vecs = emb.embed_passages(texts)
    assert vecs.shape == (3, 768)
    assert vecs.dtype == np.float32
    norms = np.linalg.norm(vecs, axis=1)
    assert np.allclose(norms, 1.0, atol=0.01)


def test_onnx_semantic_quality():
    """Related queries should be closer than unrelated."""
    from core.embedder_onnx import OnnxEmbedder
    emb = OnnxEmbedder()
    v1 = emb.embed_query("docker deploy")
    v2 = emb.embed_query("контейнер деплой")
    v3 = emb.embed_query("рецепт борща")
    sim_related = np.dot(v1, v2)
    sim_unrelated = np.dot(v1, v3)
    assert sim_related > sim_unrelated
