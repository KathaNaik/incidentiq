"""The model boundary.

One protocol, one implementation. `InvestigationModel.investigate` takes a rendered
prompt and returns parsed output; everything about *what* the model is allowed to see,
and whether its answer is acceptable, lives outside it.

The concrete provider is OpenAI's Responses API with structured outputs, so the response
arrives as a validated Pydantic object rather than JSON salvaged from prose. Note what
that does and does not buy: structured outputs guarantee the *shape* of the answer. They
say nothing about whether the evidence ids inside it exist or whether the reasoning is
sound, which is why `validate.py` still runs on every result.

No provider object crosses this boundary — callers receive `ModelResponse`.
"""

import time
from dataclasses import dataclass
from typing import Protocol

from app.investigation.models import InvestigationOutput

DEFAULT_MODEL = "gpt-5.6-terra"

# Enough room for a handful of hypotheses with citations. The output is structured, so
# there is nothing to gain from a larger budget.
MAX_OUTPUT_TOKENS = 4000

# Moderate reasoning. This is bounded evidence synthesis over a dozen supplied facts,
# not open-ended problem solving; higher effort costs latency and tokens for a task
# whose difficulty is already capped by what the registry contains.
REASONING_EFFORT = "medium"

MISSING_CREDENTIALS = (
    "no OpenAI credentials are configured, so investigation is unavailable. Set "
    "OPENAI_API_KEY. Triage, correlation and historical retrieval do not need it and "
    "are unaffected."
)


class InvestigationModelError(RuntimeError):
    """The model could not be reached, or did not return usable output."""


@dataclass(frozen=True)
class ModelResponse:
    """What the investigation layer gets back. Deliberately provider-agnostic."""

    output: InvestigationOutput
    model: str
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    # Reported by reasoning models; billed as output tokens. The reasoning *content* is
    # never requested or logged — only the count.
    reasoning_tokens: int | None = None


class InvestigationModel(Protocol):
    @property
    def model_id(self) -> str: ...

    def investigate(self, system: str, user_message: str) -> ModelResponse: ...


class OpenAIInvestigationModel:
    """OpenAI, via the Responses API's structured-output helper."""

    def __init__(self, model: str = DEFAULT_MODEL, api_key: str | None = None) -> None:
        self._model = model
        self._api_key = api_key
        self._client = None

    @property
    def model_id(self) -> str:
        return self._model

    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            import openai
        except ImportError as error:  # pragma: no cover - dependency is declared
            raise InvestigationModelError(
                "the openai package is not installed; run `uv sync` in apps/api"
            ) from error

        try:
            # Without an explicit key the SDK reads OPENAI_API_KEY, and raises if it
            # finds nothing.
            self._client = (
                openai.OpenAI(api_key=self._api_key)
                if self._api_key
                else openai.OpenAI()
            )
        except openai.OpenAIError as error:
            raise InvestigationModelError(MISSING_CREDENTIALS) from error
        return self._client

    def investigate(self, system: str, user_message: str) -> ModelResponse:
        import openai

        client = self._connect()
        started = time.perf_counter()
        try:
            response = client.responses.parse(
                model=self._model,
                instructions=system,
                input=user_message,
                text_format=InvestigationOutput,
                reasoning={"effort": REASONING_EFFORT},
                max_output_tokens=MAX_OUTPUT_TOKENS,
            )
        except openai.AuthenticationError as error:
            raise InvestigationModelError(
                f"OpenAI credentials were rejected: {error}"
            ) from error
        except openai.RateLimitError as error:
            raise InvestigationModelError(f"rate limited by OpenAI: {error}") from error
        except openai.APIStatusError as error:
            raise InvestigationModelError(
                f"OpenAI returned {error.status_code}: {error.message}"
            ) from error
        except openai.APIConnectionError as error:
            raise InvestigationModelError(f"could not reach OpenAI: {error}") from error

        latency_ms = int((time.perf_counter() - started) * 1000)
        return ModelResponse(
            output=_parsed_output(response),
            model=self._model,
            latency_ms=latency_ms,
            **_usage(response),
        )


def _parsed_output(response) -> InvestigationOutput:
    """Reads the structured result, distinguishing the ways it can be absent.

    A truncated response and a refusal are different problems with different fixes, and
    collapsing them into "no output" makes both harder to debug.
    """
    if getattr(response, "status", None) == "incomplete":
        reason = getattr(getattr(response, "incomplete_details", None), "reason", None)
        raise InvestigationModelError(
            f"the model stopped before completing its answer ({reason or 'unknown'}); "
            "the structured result is unusable"
        )

    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise InvestigationModelError(
            "the model returned no parsable investigation output"
        )
    return parsed


def _usage(response) -> dict[str, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "reasoning_tokens": None}
    details = getattr(usage, "output_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "reasoning_tokens": getattr(details, "reasoning_tokens", None),
    }
