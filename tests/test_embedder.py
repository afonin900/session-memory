import numpy as np
from core.embedder import Embedder


def test_embed_query_returns_768_dim():
    emb = Embedder()
    vec = emb.embed_query("test query")
    assert vec.shape == (768,)
    assert vec.dtype == np.float32


def test_embed_passages_batch():
    emb = Embedder()
    vecs = emb.embed_passages(["first passage", "second passage"])
    assert vecs.shape == (2, 768)


def test_embeddings_are_normalized():
    emb = Embedder()
    vec = emb.embed_query("normalized vector test")
    norm = np.linalg.norm(vec)
    assert abs(norm - 1.0) < 0.01


def test_similar_texts_have_high_cosine():
    emb = Embedder()
    v1 = emb.embed_query("деплой docker на сервер")
    v2 = emb.embed_query("установка докера на VPS")
    v3 = emb.embed_query("рецепт борща")
    sim_related = np.dot(v1, v2)
    sim_unrelated = np.dot(v1, v3)
    assert sim_related > sim_unrelated
