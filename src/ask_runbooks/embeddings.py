"""
Embedding model wrapper.

What embeddings are:
    A text embedding is a fixed-size vector of floats that encodes the *meaning* of a text.
    Texts with similar meaning produce vectors that are close together in vector space.
    We measure closeness with cosine similarity:
        1.0  = identical meaning
        0.0  = unrelated
       -1.0  = opposite meaning (rare in practice)

    Example: embed("database failover") and embed("postgres primary went down") will be
    much closer to each other than either is to embed("deploy a new feature").

Model: all-mpnet-base-v2
    - Output: 768-dimensional vectors (768 floats per text)
    - Size: ~420MB download, cached in ~/.cache/huggingface after first run
    - Quality: strong general-purpose retrieval, good MTEB scores, MPS support on Apple Silicon

normalize_embeddings=True:
    Scales each vector to unit length (magnitude = 1).
    This makes cosine similarity equivalent to dot product, which pgvector's <=> uses.
    Always use this when storing in pgvector.
"""

from __future__ import annotations

MODEL_NAME = "sentence-transformers/all-mpnet-base-v2"
EMBEDDING_DIM = 768  # must match vector(768) in the schema


import numpy as np
from sentence_transformers import SentenceTransformer

_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        print(f"Loading embedding model '{MODEL_NAME}'...")
        _model = SentenceTransformer(MODEL_NAME)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    """
    Embed a list of texts.

    Returns an ndarray of shape (len(texts), 768).
    Each row is a unit-length vector representing one text.
    """
    model = get_model()
    vectors = model.encode(
        texts,
        show_progress_bar=len(texts) > 20,
        normalize_embeddings=True,  # unit length for cosine similarity
        batch_size=64,
    )
    return vectors  # shape: (n, 768), dtype: float32


def embed_one(text: str) -> np.ndarray:
    """Embed a single text. Returns shape (384,)."""
    return embed([text])[0]
