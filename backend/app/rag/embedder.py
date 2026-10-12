"""Embeddings with fastembed (BAAI/bge-small-en-v1.5, 384 dimensions, CPU).

The model is in the Docker image. The api uses one thread for query embeddings; init uses all cores.
"""

from __future__ import annotations

import threading
from typing import Protocol

import numpy as np

from app.cache import LRUCache
from app.config import get_settings

EMBED_DIM = 384


class Embedder(Protocol):
    model_id: str

    def embed_passages(self, texts: list[str]) -> np.ndarray: ...
    def embed_query(self, text: str) -> np.ndarray: ...


class FastEmbedder:
    def __init__(self, threads: int | None = 1):
        from fastembed import TextEmbedding

        s = get_settings()
        self.model_id = f"fastembed:{s.embed_model}"
        self._model = TextEmbedding(s.embed_model, cache_dir=s.fastembed_cache_path, threads=threads)
        self._lock = threading.Lock()

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        fn = getattr(self._model, "passage_embed", None) or self._model.embed
        return np.array(list(fn(texts, batch_size=64)), dtype=np.float32)

    def embed_query(self, text: str) -> np.ndarray:
        fn = getattr(self._model, "query_embed", None)
        with self._lock:
            vecs = list(fn(text)) if fn else list(self._model.embed([text]))
        return np.asarray(vecs[0], dtype=np.float32)


class HashEmbedder:
    """Deterministic fake embedder for tests (bag of hashed words, normalized)."""

    model_id = "hash:384"

    def _vec(self, text: str) -> np.ndarray:
        import hashlib
        import re

        v = np.zeros(EMBED_DIM, dtype=np.float32)
        for w in re.findall(r"[a-z0-9]+", text.lower()):
            h = int(hashlib.md5(w.encode()).hexdigest()[:8], 16)
            v[h % EMBED_DIM] += 1.0
        n = np.linalg.norm(v)
        return v / n if n else v + 1.0 / np.sqrt(EMBED_DIM)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        return np.stack([self._vec(t) for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        return self._vec(text)


_embedder: Embedder | None = None
_lock = threading.Lock()
_query_cache = LRUCache(1024)


def get_embedder() -> Embedder:
    global _embedder
    if _embedder is None:
        with _lock:
            if _embedder is None:
                _embedder = FastEmbedder(threads=1)
    return _embedder


def set_embedder(e: Embedder | None) -> None:
    global _embedder
    _embedder = e
    _query_cache.clear()


def query_vector(text: str) -> np.ndarray:
    key = " ".join(text.lower().split())
    hit = _query_cache.get(key)
    if hit is not None:
        return hit
    v = get_embedder().embed_query(key)
    _query_cache.put(key, v)
    return v


def to_pg(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v.tolist()) + "]"
