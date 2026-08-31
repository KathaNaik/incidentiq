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
from app.embeddings.registry import MODELS, EmbeddingModelSpec


def _spec_for_name(model_name: str) -> EmbeddingModelSpec | None:
    """The registry entry for a model, or None for one not evaluated here."""
    return next(
        (spec for spec in MODELS.values() if spec.model_name == model_name), None
    )

MODEL_NAME = "BAAI/bge-small-en-v1.5"
DIMENSIONS = 384
# Fixed so repeated runs pad identically. See the reproducibility note above.
BATCH_SIZE = 32


class LocalEmbeddingProvider:
    """Embeddings from a local ONNX model. Loaded lazily on first use."""

    def __init__(self, model_name: str = MODEL_NAME) -> None:
        self._model_name = model_name
        self._model = None
        # Dimension comes from the registry, not from a module constant. It used to be
        # fixed at 384 while `model_name` was already a parameter, so constructing this
        # with any other model reported the wrong shape — a silently wrong vector rather
        # than an error.
        self._spec = _spec_for_name(model_name)

    @property
    def identity(self) -> str:
        return f"fastembed:{self._model_name}"

    @property
    def dimensions(self) -> int:
        return self._spec.dimension if self._spec else DIMENSIONS

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

        # In the container image the model is baked at a known path at build time, so a
        # cold instance answers the first historical-retrieval query without reaching the
        # internet. Unset locally, where fastembed's own default cache is correct.
        from app.config import get_settings

        cache_dir = get_settings().embedding_model_cache_dir
        options = {"cache_dir": str(cache_dir)} if cache_dir else {}

        try:
            self._model = TextEmbedding(model_name=self._model_name, **options)
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
