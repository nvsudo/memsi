"""Pluggable embedders. Changing embedder changes vector dimension: run `memctl reindex`."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine(a: list[float], b: list[float]) -> float:
    va, vb = np.asarray(a, dtype=np.float32), np.asarray(b, dtype=np.float32)
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    if na == 0 or nb == 0:
        return 0.0
    return float(np.dot(va, vb) / (na * nb))


_WORD = re.compile(r"[a-z0-9']+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are", "was", "be", "it",
    "that", "this", "with", "as", "at", "by", "i", "my", "me", "we", "you", "he", "she", "they",
    "his", "her", "their", "our", "your", "not", "no", "do", "does", "has", "have", "had", "from",
}


class HashEmbedder:
    """Deterministic feature-hashing embedder. No download, dev/demo quality.

    Lexical overlap only: good enough to exercise dedup and neighbour detection,
    not a substitute for a semantic model. Swap for bge-small or ollama in memsi.yaml.
    """

    name = "hash"

    def __init__(self, dim: int = 256):
        self.dim = dim

    @staticmethod
    def _features(text: str) -> list[str]:
        words = [w for w in _WORD.findall(text.lower()) if w not in _STOP]
        feats = list(words)
        feats += [f"{a}_{b}" for a, b in zip(words, words[1:])]
        for w in words:
            if len(w) > 4:
                feats += [f"#{w[i:i+3]}" for i in range(len(w) - 2)]
        return feats

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype=np.float32)
        for f in self._features(text):
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if h[4] & 1 else -1.0
            weight = 0.5 if f.startswith("#") else 1.0
            v[idx] += sign * weight
        n = float(np.linalg.norm(v))
        if n > 0:
            v /= n
        return v.tolist()

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]


class OllamaEmbedder:
    name = "ollama"

    def __init__(self, model: str = "nomic-embed-text", host: str = "http://localhost:11434", dim: int = 768):
        self.model, self.host, self.dim = model, host, dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        import httpx

        r = httpx.post(f"{self.host}/api/embed", json={"model": self.model, "input": texts}, timeout=60)
        r.raise_for_status()
        return r.json()["embeddings"]


class SentenceTransformerEmbedder:
    name = "bge-small"

    def __init__(self, model: str = "BAAI/bge-small-en-v1.5", dim: int = 384):
        self.model_name, self.dim = model, dim
        self._model = None

    def _load(self):
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # pip install 'memsi[semantic]'

            self._model = SentenceTransformer(self.model_name)
        return self._model

    def embed(self, texts: list[str]) -> list[list[float]]:
        m = self._load()
        return m.encode(texts, normalize_embeddings=True).tolist()


def make_embedder(name: str) -> Embedder:
    if name == "hash":
        return HashEmbedder()
    if name == "ollama":
        return OllamaEmbedder()
    if name in ("bge-small", "sentence-transformers"):
        return SentenceTransformerEmbedder()
    raise ValueError(f"unknown embedder: {name}")
