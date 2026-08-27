"""Local ONNX embedding provider.

`BAAI/bge-small-en-v1.5` via fastembed: 384 dimensions, L2-normalized output, runs on
CPU through onnxruntime with no PyTorch and no credentials. Chosen because it makes the
evaluation actually runnable — a hosted embedding API would have left this milestone
measurable only in theory here.

**Reproducibility.** The model is bit-identical for the same input at the same batch
size; different batch sizes shift components by ~1e-4 (ONNX padding), which moves a
cosine similarity by ~1e-5. Batch size is therefore fixed, and the cache means a rerun
reuses the exact vectors rather than recomputing them.
"""

from collections.abc import Sequence

from app.embeddings.provider import EmbeddingError

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
# Fixed so repeated runs pad identically. See the reproducibility note above.
BATCH_SIZE = 32


class LocalEmbeddingProvider:
    """Embeddings from a local ONNX model. Loaded lazily on first use."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None

    @property
    def identity(self) -> str:
        return f"fastembed:{self._model_name}"

    @property
    def dimensions(self) -> int:
        return DIMENSIONS

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            from fastembed import TextEmbedding
        except ImportError as error:
            raise EmbeddingError(
                "fastembed is not installed, so semantic correlation is unavailable. "
                "Run `uv sync --group semantic` in apps/api. The deterministic "
                "baseline does not need it."
            ) from error

        try:
            self._model = TextEmbedding(model_name=self._model_name)
        except Exception as error:
            raise EmbeddingError(
                f"could not load embedding model {self._model_name}: {error}. "
                "The first run downloads it, which needs network access."
            ) from error
        return self._model

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_many([text])[0]

    def embed_many(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            return ()
        model = self._load()
        try:
            vectors = list(model.embed(list(texts), batch_size=BATCH_SIZE))
        except Exception as error:
            raise EmbeddingError(f"embedding failed: {error}") from error

        if len(vectors) != len(texts):
            raise EmbeddingError(
                f"provider returned {len(vectors)} vectors for {len(texts)} texts"
            )
        return tuple(tuple(float(value) for value in vector) for vector in vectors)
