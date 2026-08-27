"""Embedding provider boundary, canonical embedding text, and the vector cache.

Nothing here decides anything about incidents — it turns ticket text into vectors. The
decision of what a similarity *means* lives in `app.correlation`.
"""

from app.embeddings.cache import EmbeddingCache, content_key
from app.embeddings.local import MODEL_NAME, LocalEmbeddingProvider
from app.embeddings.provider import EmbeddingError, EmbeddingProvider
from app.embeddings.text import embedding_text

__all__ = [
    "MODEL_NAME",
    "EmbeddingCache",
    "EmbeddingError",
    "EmbeddingProvider",
    "LocalEmbeddingProvider",
    "content_key",
    "embedding_text",
]
