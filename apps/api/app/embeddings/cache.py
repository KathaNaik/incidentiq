"""On-disk embedding cache.

Two files per provider+model: a float32 blob of vectors and a JSON index mapping a
content hash to its row. Written with the standard library only, so the default install
needs no numeric stack to read a cache produced by the semantic extra.

The provider identity is part of both the filename and the index, and a mismatch is
refused rather than silently reused — vectors from one model are meaningless to another,
and a stale cache would quietly invalidate an evaluation.
"""

import hashlib
import json
import re
from array import array
from pathlib import Path

from app.embeddings.provider import EmbeddingError, EmbeddingProvider

INDEX_SUFFIX = ".index.json"
VECTORS_SUFFIX = ".vectors.f32"


def content_key(identity: str, text: str) -> str:
    """Hash of the exact text that will be embedded, scoped to the model."""
    digest = hashlib.sha256()
    digest.update(identity.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def _slug(identity: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", identity)


class EmbeddingCache:
    """Reuses vectors across runs so an evaluation is reproducible and cheap."""

    def __init__(self, directory: Path, provider: EmbeddingProvider) -> None:
        self._directory = directory
        self._identity = provider.identity
        self._dimensions = provider.dimensions
        self._base = directory / _slug(self._identity)
        self._rows: dict[str, int] = {}
        self._vectors = array("f")
        self._dirty = False
        self._load()

    @property
    def size(self) -> int:
        return len(self._rows)

    def _load(self) -> None:
        index_path = Path(f"{self._base}{INDEX_SUFFIX}")
        vectors_path = Path(f"{self._base}{VECTORS_SUFFIX}")
        if not index_path.is_file() or not vectors_path.is_file():
            return

        index = json.loads(index_path.read_text(encoding="utf-8"))
        if index.get("identity") != self._identity:
            raise EmbeddingError(
                f"embedding cache at {index_path} was written by "
                f"{index.get('identity')!r}, not {self._identity!r}. Delete it rather "
                "than mixing vectors from different models."
            )
        if index.get("dimensions") != self._dimensions:
            raise EmbeddingError(
                f"embedding cache at {index_path} holds {index.get('dimensions')}-"
                f"dimensional vectors, expected {self._dimensions}."
            )

        self._vectors = array("f")
        self._vectors.frombytes(vectors_path.read_bytes())
        self._rows = {key: int(row) for key, row in index["rows"].items()}

        expected = len(self._rows) * self._dimensions
        if len(self._vectors) != expected:
            raise EmbeddingError(
                f"embedding cache is inconsistent: {len(self._vectors)} floats for "
                f"{len(self._rows)} vectors. Delete it and rebuild."
            )

    def get(self, text: str) -> tuple[float, ...] | None:
        row = self._rows.get(content_key(self._identity, text))
        if row is None:
            return None
        start = row * self._dimensions
        return tuple(self._vectors[start : start + self._dimensions])

    def put(self, text: str, vector: tuple[float, ...]) -> None:
        if len(vector) != self._dimensions:
            raise EmbeddingError(
                f"expected a {self._dimensions}-dimensional vector, got {len(vector)}"
            )
        key = content_key(self._identity, text)
        if key in self._rows:
            return
        self._rows[key] = len(self._vectors) // self._dimensions
        self._vectors.extend(vector)
        self._dirty = True

    def save(self) -> None:
        """Writes both files atomically, and only when something changed."""
        if not self._dirty:
            return
        self._directory.mkdir(parents=True, exist_ok=True)

        vectors_path = Path(f"{self._base}{VECTORS_SUFFIX}")
        index_path = Path(f"{self._base}{INDEX_SUFFIX}")
        vectors_temp = vectors_path.with_suffix(".partial")
        index_temp = index_path.with_suffix(".partial")

        vectors_temp.write_bytes(self._vectors.tobytes())
        index_temp.write_text(
            json.dumps(
                {
                    "identity": self._identity,
                    "dimensions": self._dimensions,
                    "rows": self._rows,
                },
                indent=0,
            ),
            encoding="utf-8",
        )
        vectors_temp.replace(vectors_path)
        index_temp.replace(index_path)
        self._dirty = False
