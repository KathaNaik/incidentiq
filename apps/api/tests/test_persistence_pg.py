"""Durability, against a real PostgreSQL.

Everything here needs the database that the fast suite deliberately avoids. These are
the guarantees a fake cannot assert about itself: a partial unique index that stops two
concurrent investigations, a unique constraint that makes execution idempotent across a
restart, and the fact that an empty database plus migrations produces a working system.

Restart is simulated the only honest way — by constructing a *new* repository against a
*new* session. An in-memory flag would survive an object being rebuilt inside one
process; a row in PostgreSQL is what survives the process going away.

Skipped, not failed, when no database is configured: a contributor without Docker running
should still be able to run the suite.
"""

import os
import subprocess
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text

pytestmark = pytest.mark.pg

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    from app.config import get_settings

    DATABASE_URL = get_settings().database_url

if not DATABASE_URL:  # pragma: no cover - environment dependent
    pytest.skip(
        "no DATABASE_URL; start PostgreSQL with `docker compose up -d`",
        allow_module_level=True,
    )

from app.actions import (  # noqa: E402
    ActionStatus,
    ActorType,
    approve_action,
    execute_action,
    propose_action,
    reject_action,
)
from app.actions.repository import ConcurrentModificationError  # noqa: E402
from app.db.action_store import SqlActionRepository  # noqa: E402
from app.db.engine import get_engine  # noqa: E402
from app.db.investigation_store import (  # noqa: E402
    ActiveRunExistsError,
    InvestigationRunStore,
)
from app.db.models import EMBEDDING_DIMENSIONS  # noqa: E402
from app.db.retrieval_store import PgVectorHistoricalIndex, RetrievalFilters  # noqa: E402
from app.investigation.rules import INVESTIGATION_VERSION  # noqa: E402
from app.retrieval.models import RetrievalQuery  # noqa: E402
from evaluation.policy import (  # noqa: E402
    CORRELATION,
    DEPLOYMENT,
    ERROR,
    HEALTH,
    _investigation,
    _remediation,
)
from app.investigation.models import RemediationAction  # noqa: E402
from tests.test_actions import OPERATIONS  # noqa: E402


@pytest.fixture
def engine():
    return get_engine()


@pytest.fixture
def clean(engine):
    """A workflow-empty database. The historical corpus is left alone."""
    with engine.begin() as connection:
        for table in (
            "audit_events",
            "execution_results",
            "approvals",
            "actions",
            "investigation_runs",
        ):
            connection.execute(text(f"DELETE FROM {table}"))
    return engine


def investigation(incident_id: str):
    return _investigation(
        remediation=_remediation(
            RemediationAction.ROLLBACK_DEPLOYMENT,
            (DEPLOYMENT.id, HEALTH.id, ERROR.id),
        ),
        evidence=(CORRELATION, DEPLOYMENT, HEALTH, ERROR),
        incident_id=incident_id,
    )


def store_run(store: InvestigationRunStore, incident_id: str, *, prompt="investigation-v2"):
    result = investigation(incident_id)
    run = store.begin(
        incident_id=incident_id,
        investigator_version=INVESTIGATION_VERSION,
        prompt_version=prompt,
        provider="openai",
        model="gpt-5.6-terra",
        evidence=result.evidence,
    )
    return store.complete(
        run.id,
        output=result.output,
        model="gpt-5.6-terra",
        latency_ms=1234,
        input_tokens=100,
        output_tokens=50,
        reasoning_tokens=25,
    )


def incident() -> str:
    return f"cand-{uuid.uuid4().hex[:8]}"


# --- migrations -------------------------------------------------------------------------


def test_an_empty_database_reaches_the_current_schema(clean, engine) -> None:
    """Migrations, not create_all, are the schema-management strategy."""
    result = subprocess.run(
        ["uv", "run", "alembic", "upgrade", "head"],
        capture_output=True,
        text=True,
        cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    )
    assert result.returncode == 0, result.stderr

    with engine.connect() as connection:
        tables = set(
            connection.execute(
                text("SELECT tablename FROM pg_tables WHERE schemaname='public'")
            ).scalars()
        )
    assert {
        "actions",
        "approvals",
        "audit_events",
        "execution_results",
        "historical_incidents",
        "investigation_runs",
        "alembic_version",
    } <= tables


def test_pgvector_is_installed_with_the_expected_dimension(engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT 1 FROM pg_extension WHERE extname='vector'")
        ).scalar_one_or_none() == 1
        dimension = connection.execute(
            text(
                "SELECT atttypmod FROM pg_attribute "
                "WHERE attrelid='historical_incidents'::regclass AND attname='embedding'"
            )
        ).scalar_one()
    assert dimension == EMBEDDING_DIMENSIONS


# --- investigation runs -------------------------------------------------------------------


def test_a_run_persists_its_exact_evidence_snapshot(clean) -> None:
    """The snapshot is the record. It must not be rebuilt from current fixtures."""
    store = InvestigationRunStore()
    incident_id = incident()
    run = store_run(store, incident_id)

    reread = InvestigationRunStore().get(run.id)

    assert reread is not None
    assert reread.status == "succeeded"
    assert [item.id for item in reread.evidence] == [
        CORRELATION.id, DEPLOYMENT.id, HEALTH.id, ERROR.id
    ]
    assert reread.output is not None
    assert reread.output.remediation is not None
    assert reread.prompt_version == "investigation-v2"
    assert reread.provider == "openai"
    assert reread.reasoning_tokens == 25


def test_a_rerun_creates_a_new_run_and_leaves_the_old_one_untouched(clean) -> None:
    store = InvestigationRunStore()
    incident_id = incident()

    first = store_run(store, incident_id)
    before = InvestigationRunStore().get(first.id)
    second = store_run(store, incident_id)

    assert second.id != first.id
    after = InvestigationRunStore().get(first.id)
    assert after == before, "an earlier run must be exactly what it was"

    history = store.history(incident_id)
    assert [run.id for run in history] == [second.id, first.id]
    assert store.latest_successful(incident_id).id == second.id


def test_a_failed_rerun_preserves_the_previous_successful_answer(clean) -> None:
    """A provider outage must not erase the conclusion an operator is relying on."""
    store = InvestigationRunStore()
    incident_id = incident()
    good = store_run(store, incident_id)

    failing = store.begin(
        incident_id=incident_id,
        investigator_version=INVESTIGATION_VERSION,
        prompt_version="investigation-v2",
        provider="openai",
        model="gpt-5.6-terra",
        evidence=investigation(incident_id).evidence,
    )
    store.fail(failing.id, failure_type="provider_error", message="provider unavailable")

    fresh = InvestigationRunStore()
    assert fresh.latest_successful(incident_id).id == good.id
    assert fresh.latest(incident_id).id == failing.id
    assert fresh.get(failing.id).failure_type == "provider_error"
    assert fresh.get(failing.id).output is None
    assert len(fresh.history(incident_id)) == 2


def test_only_one_investigation_can_be_active_per_incident(clean) -> None:
    """The duplicate-model-call guard, enforced by the database not by a check."""
    store = InvestigationRunStore()
    incident_id = incident()
    first = store.begin(
        incident_id=incident_id,
        investigator_version=INVESTIGATION_VERSION,
        prompt_version="investigation-v2",
        provider="openai",
        model="gpt-5.6-terra",
        evidence=investigation(incident_id).evidence,
    )

    with pytest.raises(ActiveRunExistsError) as caught:
        InvestigationRunStore().begin(
            incident_id=incident_id,
            investigator_version=INVESTIGATION_VERSION,
            prompt_version="investigation-v2",
            provider="openai",
            model="gpt-5.6-terra",
            evidence=(),
        )
    assert caught.value.run.id == first.id, "the caller is handed the run already in flight"

    # Once it finishes, a new one is allowed.
    store.fail(first.id, failure_type="provider_error", message="done")
    assert store.begin(
        incident_id=incident_id,
        investigator_version=INVESTIGATION_VERSION,
        prompt_version="investigation-v2",
        provider="openai",
        model="gpt-5.6-terra",
        evidence=(),
    ).id != first.id


def test_a_completed_run_is_immutable(clean) -> None:
    store = InvestigationRunStore()
    run = store_run(store, incident())

    with pytest.raises(ValueError, match="immutable"):
        store.fail(run.id, failure_type="nope", message="should not be possible")


def test_v1_metadata_round_trips(clean) -> None:
    """v1 stays historically reachable, and a run says which investigator produced it."""
    store = InvestigationRunStore()
    incident_id = incident()
    run = store_run(store, incident_id, prompt="investigation-v1")

    assert InvestigationRunStore().get(run.id).prompt_version == "investigation-v1"


# --- actions, approvals, executions ---------------------------------------------------------


def propose(repository, store, incident_id):
    run = store_run(store, incident_id)
    action = propose_action(
        investigation=run.as_result(),
        operations=OPERATIONS,
        repository=repository,
        service_id="svc-auth",
        investigation_run_id=run.id,
    )
    return action, run


def test_an_action_survives_a_new_repository_and_names_its_source_run(clean) -> None:
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    incident_id = incident()
    action, run = propose(repository, store, incident_id)

    # A brand new repository over a brand new session: what a restarted API would see.
    reread = SqlActionRepository().get(action.id)

    assert reread.investigation_run_id == run.id
    assert reread.status is ActionStatus.AWAITING_APPROVAL
    assert reread.policy.eligible is True
    assert len(reread.policy.reasons) == len(action.policy.reasons)
    assert reread.target.deployment_id == "DEP-2041"


def test_reinvestigating_does_not_repoint_an_existing_action(clean) -> None:
    """An approved action stays attached to the run that actually justified it."""
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    incident_id = incident()
    action, first_run = propose(repository, store, incident_id)

    second_run = store_run(store, incident_id)

    assert store.latest_successful(incident_id).id == second_run.id
    assert SqlActionRepository().get(action.id).investigation_run_id == first_run.id


def test_approval_persists_and_a_repeat_is_refused(clean) -> None:
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    action, _ = propose(repository, store, incident())

    approve_action(action_id=action.id, repository=repository)

    reread = SqlActionRepository().get(action.id)
    assert reread.status is ActionStatus.APPROVED
    assert reread.approval is not None
    assert reread.approval.actor_type is ActorType.HUMAN

    # Deterministic on repeat: the state machine refuses, so no second approval row.
    with pytest.raises(Exception):
        approve_action(action_id=action.id, repository=SqlActionRepository())
    assert SqlActionRepository().get(action.id).approval.id == reread.approval.id


def test_a_rejected_action_persists_and_cannot_execute(clean) -> None:
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    action, _ = propose(repository, store, incident())

    reject_action(action_id=action.id, repository=repository)
    reread = SqlActionRepository().get(action.id)

    assert reread.status is ActionStatus.REJECTED
    assert reread.approval.approved is False

    with pytest.raises(Exception):
        execute_action(
            action_id=action.id,
            repository=SqlActionRepository(),
            operations=OPERATIONS,
        )
    assert SqlActionRepository().get(action.id).execution is None


def test_execution_is_idempotent_across_a_simulated_restart(clean) -> None:
    """The mandatory acceptance behaviour of this milestone.

    A fresh repository over a fresh session is what a restarted API has. The second
    execute must return the original result and must not run the side effect again.
    """
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    action, _ = propose(repository, store, incident())
    approve_action(action_id=action.id, repository=repository)

    first = execute_action(
        action_id=action.id, repository=repository, operations=OPERATIONS
    )
    assert first.status is ActionStatus.SUCCEEDED
    assert first.execution.simulated is True

    # --- restart ---
    restarted = SqlActionRepository()
    second = execute_action(
        action_id=action.id, repository=restarted, operations=OPERATIONS
    )

    assert second.status is ActionStatus.SUCCEEDED
    assert second.execution.executed_at == first.execution.executed_at
    assert second.execution.summary == first.execution.summary

    # And exactly one execution row exists, whatever the caller believed.
    with get_engine().connect() as connection:
        count = connection.execute(
            text("SELECT count(*) FROM execution_results WHERE action_id = :id"),
            {"id": action.id},
        ).scalar_one()
    assert count == 1, "the database refuses a second execution result"

    skipped = [
        event
        for event in restarted.audit_for_action(action.id)
        if event.event_type.value == "execution_skipped_idempotent"
    ]
    assert len(skipped) == 1, "the duplicate attempt is recorded, not silent"


def test_dashboard_counts_come_from_durable_state(clean) -> None:
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    action, _ = propose(repository, store, incident())
    approve_action(action_id=action.id, repository=repository)
    execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)

    rows = SqlActionRepository().all()
    assert [row.status for row in rows] == [ActionStatus.SUCCEEDED]


# --- audit ---------------------------------------------------------------------------------


def test_the_audit_trail_persists_in_order_with_correct_attribution(clean) -> None:
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    action, run = propose(repository, store, incident())
    approve_action(action_id=action.id, repository=repository)
    execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)

    events = SqlActionRepository().audit_for_action(action.id)
    kinds = [event.event_type.value for event in events]

    assert kinds == [
        "recommendation_received",
        "action_proposed",
        "policy_evaluated",
        "approval_granted",
        "execution_started",
        "execution_succeeded",
    ]
    by_type = {event.event_type.value: event for event in events}
    assert by_type["recommendation_received"].actor_type is ActorType.MODEL
    assert by_type["approval_granted"].actor_type is ActorType.HUMAN
    assert by_type["execution_succeeded"].actor_type is ActorType.SYSTEM
    assert by_type["recommendation_received"].investigation_run_id == run.id

    # Deterministic: repeated reads return the same order.
    assert [e.id for e in SqlActionRepository().audit_for_action(action.id)] == [
        e.id for e in events
    ]


def test_the_database_refuses_to_attribute_an_execution_to_the_model(clean) -> None:
    """The actor boundary, enforced below the service layer."""
    with pytest.raises(Exception):
        with get_engine().begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO audit_events "
                    "(id, sequence, incident_id, event_type, actor_type, actor_id, "
                    " occurred_at, details) "
                    "VALUES ('aud-bad', 999999, 'cand-x', 'execution_succeeded', "
                    "'model', 'model:evil', now(), '{}'::jsonb)"
                )
            )


# --- historical corpus and pgvector -----------------------------------------------------------


@pytest.fixture(scope="module")
def index():
    from app.embeddings import LocalEmbeddingProvider

    return PgVectorHistoricalIndex(LocalEmbeddingProvider())


def test_the_corpus_is_populated_with_vectors(engine) -> None:
    with engine.connect() as connection:
        total, embedded = connection.execute(
            text(
                "SELECT count(*), count(embedding) FROM historical_incidents"
            )
        ).one()
        sources = dict(
            connection.execute(
                text("SELECT provenance, count(*) FROM historical_incidents GROUP BY 1")
            ).all()
        )
    assert total == embedded, "every record must carry a vector"
    assert total > 700
    assert set(sources) == {"northstar-authored", "itsm-mit"}
    assert "polaris" not in " ".join(sources).lower(), (
        "Polaris is external evaluation data and must never enter the application corpus"
    )


def test_every_row_records_the_model_that_embedded_it(engine) -> None:
    """So vectors cannot be silently reinterpreted with a different model later."""
    with engine.connect() as connection:
        identities = set(
            connection.execute(
                text(
                    "SELECT DISTINCT embedding_provider || ':' || embedding_model "
                    "FROM historical_incidents"
                )
            ).scalars()
        )
    assert identities == {"fastembed:BAAI/bge-small-en-v1.5"}


def test_retrieval_ranks_the_authored_precedent_first(index) -> None:
    """The Northstar regression: the SSO case must still lead on an auth query."""
    result = index.search(
        RetrievalQuery(
            text="SSO sign-in fails with invalid assertion for the whole team",
            services=("svc-auth",),
            error_identifiers=("ERR_SAML_INVALID_ASSERTION",),
        ),
        k=5,
    )
    assert result.hits[0].incident.id == "NS-HIST-0002"
    assert result.strong_match is True
    assert result.version == "historical-retrieval-v1"
    assert result.hits[0].incident.provenance.value == "northstar-authored"


def test_pgvector_ranking_matches_the_reference_implementation(index) -> None:
    """The migration must not have changed what the product returns.

    The in-memory index is kept as a reference implementation for exactly this. It is not
    reachable from any request path.
    """
    from app.config import get_settings
    from app.embeddings import EmbeddingCache, LocalEmbeddingProvider
    from app.retrieval import HistoricalIndex, load_corpus

    settings = get_settings()
    provider = LocalEmbeddingProvider()
    reference = HistoricalIndex(provider, EmbeddingCache(settings.embeddings_cache_dir, provider))
    reference.build(load_corpus(settings.fixtures_dir, settings.itsm_processed_dir))

    for query in (
        RetrievalQuery(
            text="SSO sign-in fails with invalid assertion",
            services=("svc-auth",),
            error_identifiers=("ERR_SAML_INVALID_ASSERTION",),
        ),
        RetrievalQuery(text="sync jobs stuck, queue growing", services=("svc-connector",)),
        RetrievalQuery(text="cannot print to the office printer"),
    ):
        expected = reference.search(query, k=5)
        actual = index.search(query, k=5)
        assert [h.incident.id for h in actual.hits] == [
            h.incident.id for h in expected.hits
        ], query.text
        for a, b in zip(actual.hits, expected.hits, strict=True):
            assert abs(a.score - b.score) < 1e-4, query.text
        assert actual.strong_match == expected.strong_match


def test_ranking_is_deterministic_and_ties_break_on_id(index) -> None:
    query = RetrievalQuery(text="password reset request")
    first = index.search(query, k=10)
    second = index.search(query, k=10)

    assert [h.incident.id for h in first.hits] == [h.incident.id for h in second.hits]
    scores = [h.score for h in first.hits]
    assert scores == sorted(scores, reverse=True)
    # Ties resolve on id ascending.
    for a, b in zip(first.hits, first.hits[1:], strict=False):
        if a.score == b.score:
            assert a.incident.id < b.incident.id


def test_exclude_holds_a_record_out(index) -> None:
    query = RetrievalQuery(text="SSO sign-in fails with invalid assertion")
    full = index.search(query, k=5)
    held = index.search(query, k=5, exclude=frozenset({full.hits[0].incident.id}))

    assert full.hits[0].incident.id not in [h.incident.id for h in held.hits]
    assert held.corpus_size == full.corpus_size - 1


def test_metadata_filtering_narrows_before_ranking(index) -> None:
    """The capability the move to SQL buys. Unused by default retrieval."""
    result = index.search(
        RetrievalQuery(text="sign-in problems"),
        k=5,
        filters=RetrievalFilters(provenance=("northstar-authored",)),
    )
    assert result.hits
    assert all(
        hit.incident.provenance.value == "northstar-authored" for hit in result.hits
    )


def test_no_root_cause_or_resolution_reaches_the_query(index) -> None:
    """The M7 leakage boundary, preserved through the migration.

    The corpus rows carry root causes; the query text must never contain one, or
    retrieval would be matching answers to answers.
    """
    result = index.search(
        RetrievalQuery(
            text="users cannot sign in",
            services=("svc-auth",),
            error_identifiers=("ERR_SAML_INVALID_ASSERTION",),
        ),
        k=5,
    )
    top = result.hits[0].incident

    assert top.outcome.root_cause, "the outcome is returned after a match"
    assert top.outcome.root_cause.lower() not in result.query_text.lower()
    for step in top.outcome.resolution_steps:
        assert step.lower() not in result.query_text.lower()
    # RetrievalQuery structurally cannot carry one.
    assert not hasattr(RetrievalQuery, "root_cause")


def test_retrieval_works_from_a_freshly_constructed_index(index) -> None:
    """No corpus rebuild, no warm-up: a restarted process queries the database directly."""
    from app.embeddings import LocalEmbeddingProvider

    fresh = PgVectorHistoricalIndex(LocalEmbeddingProvider())
    assert fresh.size > 700
    assert fresh.search(RetrievalQuery(text="printer offline"), k=3).hits


# --- demo reset ---------------------------------------------------------------------------


def test_demo_reset_clears_workflow_state_but_not_the_corpus(clean, engine) -> None:
    repository = SqlActionRepository()
    store = InvestigationRunStore()
    action, run = propose(repository, store, incident())
    approve_action(action_id=action.id, repository=repository)
    execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)

    with engine.connect() as connection:
        corpus_before = connection.execute(
            text("SELECT count(*) FROM historical_incidents")
        ).scalar_one()

    removed = SqlActionRepository().reset_workflow_state(store)

    assert removed >= 1
    assert SqlActionRepository().all() == ()
    assert list(SqlActionRepository().audit()) == []
    assert InvestigationRunStore().get(run.id) is None

    with engine.connect() as connection:
        assert (
            connection.execute(
                text("SELECT count(*) FROM historical_incidents")
            ).scalar_one()
            == corpus_before
        ), "the historical corpus is not workflow state"
        for table in ("actions", "approvals", "execution_results", "audit_events"):
            assert (
                connection.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
                == 0
            )
