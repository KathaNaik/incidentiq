"""The OpenAI provider adapter, tested without network access.

Every test here drives a fake SDK object. The point is the adapter's behaviour — what it
extracts, what it translates, what it refuses — not OpenAI's.
"""

import sys
import types

import pytest

from app.investigation.models import (
    InvestigationOutput,
    NextStepAction,
    RecommendedNextStep,
)
from app.investigation.provider import (
    DEFAULT_MODEL,
    MAX_OUTPUT_TOKENS,
    REASONING_EFFORT,
    InvestigationModelError,
    OpenAIInvestigationModel,
    _parsed_output,
    _usage,
)

OUTPUT = InvestigationOutput(
    hypotheses=(),
    missing_evidence=("service health",),
    recommended_next_step=RecommendedNextStep(
        action_type=NextStepAction.INSPECT_LOGS,
        description="Check the auth logs.",
        rationale="Narrows the failure.",
    ),
    abstain=True,
)


class FakeUsage:
    def __init__(self, reasoning: int | None = 128) -> None:
        self.input_tokens = 900
        self.output_tokens = 220
        self.output_tokens_details = types.SimpleNamespace(reasoning_tokens=reasoning)


class FakeResponse:
    def __init__(self, parsed=OUTPUT, status="completed", usage=None, reason=None) -> None:
        self.output_parsed = parsed
        self.status = status
        self.usage = usage
        self.incomplete_details = types.SimpleNamespace(reason=reason)


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self._response = response or FakeResponse(usage=FakeUsage())
        self._error = error
        self.kwargs: dict = {}

    def parse(self, **kwargs):
        self.kwargs = kwargs
        if self._error is not None:
            raise self._error
        return self._response


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def model_with(client: FakeClient) -> OpenAIInvestigationModel:
    model = OpenAIInvestigationModel(api_key="test-key")
    model._client = client
    return model


# --- request shape --------------------------------------------------------------------


def test_request_uses_structured_outputs_and_moderate_reasoning() -> None:
    responses = FakeResponses()
    result = model_with(FakeClient(responses)).investigate("SYSTEM", "USER")

    assert responses.kwargs["model"] == DEFAULT_MODEL
    assert responses.kwargs["instructions"] == "SYSTEM"
    assert responses.kwargs["input"] == "USER"
    # SDK-native parsing against our own schema, not JSON-in-prose.
    assert responses.kwargs["text_format"] is InvestigationOutput
    assert responses.kwargs["reasoning"] == {"effort": REASONING_EFFORT}
    assert responses.kwargs["max_output_tokens"] == MAX_OUTPUT_TOKENS
    assert result.output is OUTPUT


def test_provider_response_objects_do_not_leak_outward() -> None:
    """The investigation layer sees ModelResponse, never an SDK type."""
    result = model_with(FakeClient(FakeResponses())).investigate("s", "u")

    assert type(result).__name__ == "ModelResponse"
    assert isinstance(result.output, InvestigationOutput)
    assert result.model == DEFAULT_MODEL
    assert result.latency_ms >= 0


# --- usage metadata --------------------------------------------------------------------


def test_usage_metadata_is_extracted_including_reasoning_tokens() -> None:
    result = model_with(FakeClient(FakeResponses())).investigate("s", "u")

    assert result.input_tokens == 900
    assert result.output_tokens == 220
    assert result.reasoning_tokens == 128


def test_missing_usage_is_reported_as_unknown_not_zero() -> None:
    """Absent metering is not the same as free."""
    assert _usage(types.SimpleNamespace(usage=None)) == {
        "input_tokens": None,
        "output_tokens": None,
        "reasoning_tokens": None,
    }


def test_usage_without_reasoning_details_still_reads() -> None:
    response = types.SimpleNamespace(
        usage=types.SimpleNamespace(input_tokens=10, output_tokens=5)
    )

    assert _usage(response) == {
        "input_tokens": 10,
        "output_tokens": 5,
        "reasoning_tokens": None,
    }


# --- failure handling -------------------------------------------------------------------


def test_truncated_response_is_distinguished_from_no_output() -> None:
    """A cut-off answer and a refusal need different fixes; both must not read as one."""
    response = FakeResponse(parsed=None, status="incomplete", reason="max_output_tokens")

    with pytest.raises(InvestigationModelError, match="stopped before completing"):
        _parsed_output(response)


def test_unparsable_output_is_rejected() -> None:
    with pytest.raises(InvestigationModelError, match="no parsable investigation output"):
        _parsed_output(FakeResponse(parsed=None))


def test_sdk_errors_are_translated(monkeypatch: pytest.MonkeyPatch) -> None:
    import openai

    cases = [
        (
            openai.AuthenticationError(
                "bad key", response=_http_response(401), body=None
            ),
            "credentials were rejected",
        ),
        (
            openai.RateLimitError("slow down", response=_http_response(429), body=None),
            "rate limited",
        ),
        (openai.APIConnectionError(request=_http_request()), "could not reach OpenAI"),
    ]
    for error, expected in cases:
        model = model_with(FakeClient(FakeResponses(error=error)))
        with pytest.raises(InvestigationModelError, match=expected):
            model.investigate("s", "u")


def test_missing_api_key_produces_a_configuration_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key must never mean a fabricated investigation."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(InvestigationModelError, match="OPENAI_API_KEY"):
        OpenAIInvestigationModel().investigate("s", "u")


def test_the_provider_never_reaches_the_network_in_tests() -> None:
    """Guard against a future edit that constructs a real client during unit tests."""
    model = OpenAIInvestigationModel(api_key="test-key")
    model._client = FakeClient(FakeResponses())

    model.investigate("s", "u")

    assert "openai" in sys.modules  # imported, but no request was made


def _http_response(status: int):
    import httpx

    return httpx.Response(status_code=status, request=_http_request())


def _http_request():
    import httpx

    return httpx.Request("POST", "https://api.openai.com/v1/responses")
