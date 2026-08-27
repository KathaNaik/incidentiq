"""Historical retrieval, tested with a stub provider — no model, no network."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.correlation import CorrelationTicket, correlate
from app.dependencies import get_retrieval_index
from app.embeddings import EmbeddingCache, EmbeddingError
from app.retrieval import (
    RETRIEVAL_VERSION,
    CorpusError,
    HistoricalIncident,
    HistoricalIndex,
    HistoricalOutcome,
    Provenance,
    RetrievalQuery,
    index_text,
    load_northstar,
    query_from_tickets,
    query_text,
)
from app.retrieval.corpus import families, family_of
from app.retrieval.rules import MAX_K, STRONG_MATCH_SCORE
from evaluation.retrieval import query_for
from tests.test_semantic_correlation import BrokenProvider, StubProvider

START = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)

SECRET_CAUSE = "a rotated credential the workers never re-read"
SECRET_FIX = "roll the workers so they re-read the secret"


def historical(
    id: str,
    title: str,
    summary: str = "Symptoms as reported.",
    services=(),
    errors=(),
    provenance: Provenance = Provenance.NORTHSTAR,
) -> HistoricalIncident:
    return HistoricalIncident(
        id=id,
        title=title,
        summary=summary,
        services=tuple(services),
        observed_errors=tuple(errors),
        provenance=provenance,
        outcome=HistoricalOutcome(root_cause=SECRET_CAUSE, resolution_steps=(SECRET_FIX,)),
    )


def build_index(records, vectors: dict[str, tuple[float, ...]]) -> HistoricalIndex:
    provider = StubProvider({index_text(r): vectors[r.id] for r in records})
    index = HistoricalIndex(provider)
    index.build(records)
    return index


# --- canonical text and leakage ------------------------------------------------------


def test_index_text_excludes_the_answer() -> None:
    """The whole design rests on this: retrieval matches symptoms, and the cause is
    only revealed after a match. Embedding the cause would match answers to answers."""
    record = historical("H1", "Connector syncs failing", "Syncs abort with a 401.")

    text = index_text(record)

    assert "Connector syncs failing" in text
    assert SECRET_CAUSE not in text
    assert SECRET_FIX not in text


def test_index_text_carries_observable_context() -> None:
    record = historical(
        "H1", "Sync failing", "Aborts.", services=("svc-connector",), errors=("401",)
    )

    text = index_text(record)

    assert "svc-connector" in text
    assert "401" in text


def test_query_text_is_built_only_from_observable_fields() -> None:
    query = RetrievalQuery(
        text="Dashboards are blank", services=("svc-analytics",), error_identifiers=("503",)
    )

    text = query_text(query)

    assert "Dashboards are blank" in text
    assert "svc-analytics" in text
    assert "503" in text


def test_query_model_has_no_field_for_an_answer() -> None:
    """A root cause cannot be passed into a query even by mistake."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        RetrievalQuery(text="Dashboards blank", root_cause=SECRET_CAUSE)
    with pytest.raises(ValidationError):
        RetrievalQuery(text="Dashboards blank", event_id="EVT-1")


def test_query_from_tickets_uses_only_ticket_evidence() -> None:
    tickets = [
        CorrelationTicket(
            id="T1",
            title="Connector sync failing with ERR_SYNC_412",
            description="Every run aborts and returns a 401.",
            created_at=START,
            service_id="svc-connector",
        )
    ]

    query = query_from_tickets(tickets)

    assert "ERR_SYNC_412" in query.text
    assert "svc-connector" in query.services
    assert "err_sync_412" in query.error_identifiers
    assert "401" in query.error_identifiers
    assert SECRET_CAUSE not in query_text(query)


def test_query_from_tickets_requires_a_ticket() -> None:
    with pytest.raises(ValueError, match="at least one ticket"):
        query_from_tickets([])


def test_evaluation_queries_do_not_copy_curated_fields() -> None:
    """The eval query is what a reporter would have written, not the corpus's tidy
    services/errors columns — otherwise the benchmark measures bookkeeping."""
    record = historical(
        "H1", "Sync failing", "Aborts every run.", services=("Snowflake",), errors=("401",)
    )

    query = query_for(record)

    assert query.services == ()
    assert "Snowflake" not in query_text(query)


# --- index and ranking ---------------------------------------------------------------


def test_top_k_is_ordered_by_score() -> None:
    records = [
        historical("H1", "Connector sync failing"),
        historical("H2", "Dashboard blank"),
        historical("H3", "Slow reports"),
    ]
    index = build_index(
        records,
        {"H1": (1.0, 0.0, 0.0), "H2": (0.8, 0.6, 0.0), "H3": (0.0, 1.0, 0.0)},
    )
    provider = StubProvider({query_text(RetrievalQuery(text="q")): (1.0, 0.0, 0.0)})
    index._provider = provider  # the query embedding is what varies in this test

    result = index.search(RetrievalQuery(text="q"), k=3)

    assert [hit.incident.id for hit in result.hits] == ["H1", "H2", "H3"]
    assert result.hits[0].score >= result.hits[1].score >= result.hits[2].score
    assert [hit.rank for hit in result.hits] == [1, 2, 3]


def test_identical_scores_break_ties_on_id() -> None:
    """Two records the model cannot separate must still come back in a stable order."""
    records = [historical("H2", "Same"), historical("H1", "Same")]
    index = build_index(records, {"H1": (1.0, 0.0, 0.0), "H2": (1.0, 0.0, 0.0)})

    first = index.search(RetrievalQuery(text="q"), k=2)
    second = index.search(RetrievalQuery(text="q"), k=2)

    assert [hit.incident.id for hit in first.hits] == ["H1", "H2"]
    assert first.model_dump_json() == second.model_dump_json()


def test_k_is_honoured_and_bounded() -> None:
    records = [historical(f"H{i}", f"Case {i}") for i in range(6)]
    index = build_index(records, {r.id: (1.0, float(i), 0.0) for i, r in enumerate(records)})

    assert len(index.search(RetrievalQuery(text="q"), k=2).hits) == 2

    with pytest.raises(ValueError, match="k must be between"):
        index.search(RetrievalQuery(text="q"), k=0)
    with pytest.raises(ValueError, match="k must be between"):
        index.search(RetrievalQuery(text="q"), k=MAX_K + 1)


def test_excluded_records_are_not_returned() -> None:
    """Leave-one-out is what keeps the evaluation from measuring self-retrieval."""
    records = [historical("H1", "Connector failing"), historical("H2", "Connector down")]
    index = build_index(records, {"H1": (1.0, 0.0, 0.0), "H2": (0.9, 0.1, 0.0)})

    result = index.search(RetrievalQuery(text="q"), k=5, exclude=frozenset({"H1"}))

    assert [hit.incident.id for hit in result.hits] == ["H2"]
    assert result.corpus_size == 1


def test_searching_an_unbuilt_index_fails_loudly() -> None:
    with pytest.raises(CorpusError, match="index is empty"):
        HistoricalIndex(StubProvider()).search(RetrievalQuery(text="q"))


def test_provider_failure_propagates() -> None:
    index = HistoricalIndex(BrokenProvider())

    with pytest.raises(EmbeddingError, match="unavailable"):
        index.build([historical("H1", "Anything")])


def test_reranking_adds_service_and_identifier_evidence() -> None:
    records = [
        historical("H1", "Sync failing", services=("Connector API",), errors=("ERR_SYNC_412",)),
        historical("H2", "Sync failing", services=(), errors=()),
    ]
    index = build_index(records, {"H1": (1.0, 0.0, 0.0), "H2": (1.0, 0.0, 0.0)})

    query = RetrievalQuery(
        text="q", services=("svc-connector",), error_identifiers=("err_sync_412",)
    )
    reranked = index.search(query, k=2)
    plain = index.search(query, k=2, rerank=False)

    # Identical similarity; the shared service and error code separate them.
    assert reranked.hits[0].incident.id == "H1"
    assert {signal.kind for signal in reranked.hits[0].signals} == {
        "semantic",
        "service",
        "error_identifier",
    }
    assert plain.hits[0].score == plain.hits[1].score


def test_weak_results_are_marked_rather_than_dressed_up() -> None:
    """When nothing in the corpus resembles the query, say so."""
    records = [historical("H1", "Printer offline")]
    index = build_index(records, {"H1": (0.0, 1.0, 0.0)})
    index._provider = StubProvider({query_text(RetrievalQuery(text="q")): (1.0, 0.0, 0.0)})

    result = index.search(RetrievalQuery(text="q"), k=1)

    assert result.hits[0].score < STRONG_MATCH_SCORE
    assert result.strong_match is False


def test_hits_carry_the_outcome_for_the_operator_to_read() -> None:
    """Cause and fix are excluded from matching but are the point of the result."""
    records = [historical("H1", "Connector failing")]
    index = build_index(records, {"H1": (1.0, 0.0, 0.0)})

    hit = index.search(RetrievalQuery(text="q"), k=1).hits[0]

    assert hit.incident.outcome.root_cause == SECRET_CAUSE
    assert hit.incident.outcome.resolution_steps == (SECRET_FIX,)
    assert hit.incident.provenance is Provenance.NORTHSTAR


def test_cache_is_reused_across_index_builds(tmp_path) -> None:
    records = [historical("H1", "Connector failing")]
    provider = StubProvider({index_text(records[0]): (1.0, 0.0, 0.0)})
    cache = EmbeddingCache(tmp_path, provider)

    HistoricalIndex(provider, cache).build(records)
    calls = provider.calls
    HistoricalIndex(provider, EmbeddingCache(tmp_path, provider)).build(records)

    assert provider.calls == calls, "second build should read vectors from the cache"


# --- corpus and ground truth ---------------------------------------------------------


def test_authored_corpus_loads_with_provenance(tmp_path) -> None:
    from app.config import get_settings

    records = load_northstar(get_settings().fixtures_dir)

    assert records
    for record in records:
        assert record.provenance is Provenance.NORTHSTAR
        assert record.outcome.root_cause


def test_family_ground_truth_is_derived_from_ids_only() -> None:
    """Relevance labels come from the id prefix, which is in no text the system reads."""
    assert family_of("INC-ALP-0042") == "INC-ALP"
    grouped = families(
        [historical("INC-ALP-0001", "a"), historical("INC-ALP-0002", "b"), historical("INC-CES-0001", "c")]
    )
    assert grouped == {"INC-ALP": ["INC-ALP-0001", "INC-ALP-0002"], "INC-CES": ["INC-CES-0001"]}


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def retrieval_client(client: TestClient) -> TestClient:
    records = [
        historical("H1", "Connector syncs failing", services=("Connector API",), errors=("401",)),
        historical("H2", "Dashboards blank", services=("Analytics",)),
    ]
    index = build_index(records, {"H1": (1.0, 0.0, 0.0), "H2": (0.0, 1.0, 0.0)})
    client.app.dependency_overrides[get_retrieval_index] = lambda: index
    return client


def test_retrieval_endpoint_returns_typed_hits(retrieval_client: TestClient) -> None:
    response = retrieval_client.post(
        "/retrieval/historical-incidents",
        json={"text": "Connector syncs are failing", "services": ["svc-connector"]},
        params={"k": 2},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["version"] == RETRIEVAL_VERSION
    assert len(body["hits"]) == 2
    assert body["hits"][0]["incident"]["outcome"]["root_cause"]
    assert body["hits"][0]["incident"]["provenance"] == "northstar-authored"


def test_retrieval_endpoint_rejects_an_empty_query(retrieval_client: TestClient) -> None:
    assert (
        retrieval_client.post(
            "/retrieval/historical-incidents", json={"text": ""}
        ).status_code
        == 422
    )


def test_retrieval_endpoint_rejects_an_out_of_range_k(
    retrieval_client: TestClient,
) -> None:
    response = retrieval_client.post(
        "/retrieval/historical-incidents", json={"text": "x"}, params={"k": 999}
    )

    assert response.status_code == 422


def test_candidate_similar_endpoint(retrieval_client: TestClient) -> None:
    listed = retrieval_client.get("/correlation/candidates").json()
    candidate_id = listed["candidates"][0]["id"]

    response = retrieval_client.get(
        f"/correlation/candidates/{candidate_id}/similar", params={"k": 2}
    )

    assert response.status_code == 200
    assert response.json()["hits"]


def test_unknown_candidate_returns_404(retrieval_client: TestClient) -> None:
    response = retrieval_client.get("/correlation/candidates/cand-NOPE/similar")

    assert response.status_code == 404
    assert "cand-NOPE" in response.json()["detail"]


def test_correlation_behaviour_is_unchanged_by_this_milestone() -> None:
    """M7 touched shared modules; the evaluated correlation versions must not move."""
    tickets = [
        CorrelationTicket(
            id=name,
            title=title,
            description=description,
            created_at=START + timedelta(minutes=offset),
            service_id="svc-connector",
        )
        for name, title, description, offset in (
            ("A", "Warehouse sync stopped working", "Connector sync stopped working, no rows arrive.", 0),
            ("B", "Connector sync stopped working", "Sync stopped working, no rows arriving.", 5),
            ("C", "Permission denied writing to the warehouse", "The service account is not authorized.", 10),
        )
    ]

    result = correlate(tickets)

    assert result.version == "deterministic-correlation-v1"
    assert [candidate.ticket_ids for candidate in result.candidates] == [("A", "B")]
    assert "C" in result.standalone_ticket_ids
