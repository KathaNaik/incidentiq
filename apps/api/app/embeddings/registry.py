"""The embedding models this project has evaluated.

A small explicit table, not a plugin system. Three entries and a lookup is the whole of
what multiple models require here; anything more would be architecture for its own sake.

**Why a registry exists at all**: dimension used to be a module constant while model name
was already a constructor parameter, so building a provider for a different model
reported 384 regardless. That is the kind of mismatch that yields a working-looking
vector of the wrong shape, which is worse than a crash.

**Model identity is never guessed.** The embedding cache is keyed by `identity`, so two
models cannot read each other's vectors — a property tested rather than assumed.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class EmbeddingModelSpec:
    """One evaluated embedding model."""

    id: str
    """Short stable handle, used in eval artifacts and configuration."""

    model_name: str
    """The provider's name for it. Part of cache identity."""

    dimension: int
    provider: str = "fastembed"
    normalized: bool = True
    """Whether the provider returns unit vectors. All three here do."""

    size_gb: float | None = None
    note: str = ""

    @property
    def identity(self) -> str:
        return f"{self.provider}:{self.model_name}"


# The baseline, and not to be changed: every M6/M7/M13/M16 result was measured with it,
# and the historical retrieval corpus is embedded with it.
BGE_SMALL = EmbeddingModelSpec(
    id="bge-small",
    model_name="BAAI/bge-small-en-v1.5",
    dimension=384,
    size_gb=0.067,
    note="The evaluated baseline. Historical retrieval vectors are this model's.",
)

# Challengers, both runnable on the existing ONNX stack.
#
# `Alibaba-NLP/gte-modernbert-base` and `BAAI/bge-m3` were the brief's preferred
# challengers and are **not supported by fastembed**. Running them needs PyTorch plus a
# Transformers new enough for ModernBERT — multiple gigabytes added to answer a question
# two supported models can answer. These two were chosen instead because they come from
# *different families*: if a bge model and a gte model fail the same way, the finding is
# about the approach rather than about one model.
GTE_BASE = EmbeddingModelSpec(
    id="gte-base",
    model_name="thenlper/gte-base",
    dimension=768,
    size_gb=0.44,
    note="Different family from bge. Twice the baseline's dimension.",
)

BGE_LARGE = EmbeddingModelSpec(
    id="bge-large",
    model_name="BAAI/bge-large-en-v1.5",
    dimension=1024,
    size_gb=1.2,
    note="Same family as the baseline, roughly eighteen times the size.",
)

MODELS: dict[str, EmbeddingModelSpec] = {
    spec.id: spec for spec in (BGE_SMALL, GTE_BASE, BGE_LARGE)
}

DEFAULT_MODEL_ID = BGE_SMALL.id


def spec_for(model_id: str) -> EmbeddingModelSpec:
    if model_id not in MODELS:
        raise KeyError(
            f"unknown embedding model {model_id!r}; known: {', '.join(sorted(MODELS))}"
        )
    return MODELS[model_id]
