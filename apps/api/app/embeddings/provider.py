"""The embedding boundary.

Correlation depends on this Protocol, never on a vendor SDK. Swapping the local model
for a hosted API means writing one class, not touching the scoring code.
"""

from collections.abc import Sequence
from typing import Protocol, runtime_checkable


class EmbeddingError(RuntimeError):
    """Embeddings could not be produced.

    Raised rather than returning zeros: a silent zero vector would look like "these
    tickets are unrelated" and quietly turn semantic correlation back into the
    deterministic baseline while still reporting the semantic version.
    """


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def identity(self) -> str:
        """Stable `provider:model` string.

        Part of the cache key, so vectors from one model can never be reused by
        another.
        """
        ...

    @property
    def dimensions(self) -> int: ...

    def embed(self, text: str) -> tuple[float, ...]: ...

    def embed_many(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]: ...
