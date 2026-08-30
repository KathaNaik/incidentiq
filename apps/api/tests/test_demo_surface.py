"""The dashboard's data sources and the demo reset.

The dashboard counts things. These tests exist because a number on an operations screen
that nobody derived from a record is worse than no number at all.
"""

import pytest
from fastapi.testclient import TestClient

from app.actions import ActionRepository, ActionStatus, approve_action, execute_action
from app.config import Settings, get_settings
from app.dependencies import get_action_repository
from app.main import app
from tests.test_actions import OPERATIONS, propose


@pytest.fixture
def repository() -> ActionRepository:
    return ActionRepository()


@pytest.fixture
def client(repository: ActionRepository) -> TestClient:
    app.dependency_overrides[get_action_repository] = lambda: repository
    yield TestClient(app)
    app.dependency_overrides.pop(get_action_repository, None)


def test_actions_listing_starts_empty_rather_than_inventing_rows(client) -> None:
    response = client.get("/actions")
    assert response.status_code == 200
    assert response.json() == []


def test_actions_listing_reflects_real_workflow_state(client, repository) -> None:
    """Every count the dashboard shows must be traceable to an action that exists."""
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)

    rows = client.get("/actions").json()
    assert [row["id"] for row in rows] == [action.id]
    assert rows[0]["status"] == ActionStatus.APPROVED.value
    assert rows[0]["incident_id"] == action.incident_id

    execute_action(action_id=action.id, repository=repository, operations=OPERATIONS)
    assert client.get("/actions").json()[0]["status"] == ActionStatus.SUCCEEDED.value


def test_actions_listing_is_ordered_oldest_first(client, repository) -> None:
    first = propose(repository)
    second = propose(repository)
    assert [row["id"] for row in client.get("/actions").json()] == [first.id, second.id]


# --- demo reset -------------------------------------------------------------------------


def test_demo_reset_clears_action_and_audit_state(client, repository) -> None:
    """So a walkthrough can be run twice without restarting the API."""
    action = propose(repository)
    approve_action(action_id=action.id, repository=repository)
    assert repository.all() and repository.audit()

    body = client.post("/demo/reset").json()

    assert body["reset"] is True
    assert body["cleared_actions"] == 1
    assert body["cleared_audit_events"] > 0
    assert repository.all() == ()
    assert list(repository.audit()) == []
    assert client.get("/actions").json() == []


def test_demo_reset_is_repeatable_and_deterministic(client, repository) -> None:
    client.post("/demo/reset")
    second = client.post("/demo/reset").json()
    assert second["cleared_actions"] == 0
    assert second["cleared_audit_events"] == 0


def test_demo_reset_is_refused_in_production() -> None:
    """It discards audit events, which is never correct against real records."""
    app.dependency_overrides[get_settings] = lambda: Settings(environment="production")
    try:
        response = TestClient(app).post("/demo/reset")
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 403
    assert "disabled outside development" in response.json()["detail"]


def test_demo_reset_touches_nothing_but_action_state(client, repository) -> None:
    """Fixtures and evaluation artifacts are files on disk; reset must not reach them."""
    before = client.get("/tickets").json()
    evals_before = client.get("/evals/policy").json()

    client.post("/demo/reset")

    assert client.get("/tickets").json() == before
    assert client.get("/evals/policy").json() == evals_before


# --- policy probe ---------------------------------------------------------------------


def probe_body(action_type: str) -> dict:
    """A real investigation result, with only the action type hypothetical."""
    from evaluation.policy import CORRELATION, DEPLOYMENT, ERROR, HEALTH, _investigation

    investigation = _investigation(
        remediation=None, evidence=(CORRELATION, DEPLOYMENT, HEALTH, ERROR)
    )
    return {
        "investigation": investigation.model_dump(mode="json"),
        "action_type": action_type,
        "service_id": "svc-auth",
    }


def test_policy_probe_blocks_a_restart_against_a_configuration_failure(client) -> None:
    """The safety demo: degraded service, but a restart addresses none of it."""
    body = client.post("/demo/policy-probe", json=probe_body("restart_service")).json()

    assert body["hypothetical"] is True
    assert body["policy"]["eligible"] is False
    failed = {r["check"] for r in body["policy"]["reasons"] if not r["passed"]}
    assert "transient_runtime_failure" in failed
    assert "failure_mechanism_not_excluded" in failed


def test_policy_probe_allows_the_rollback_the_same_evidence_supports(client) -> None:
    """The rejection must be about the action, not about the evidence being weak."""
    body = client.post(
        "/demo/policy-probe", json=probe_body("rollback_deployment")
    ).json()

    assert body["policy"]["eligible"] is True


def test_policy_probe_creates_no_action_and_no_audit_trail(client, repository) -> None:
    """It answers a question. It must not become a route into the execution path."""
    client.post("/demo/policy-probe", json=probe_body("restart_service"))

    assert repository.all() == ()
    assert list(repository.audit()) == []
    assert client.get("/actions").json() == []


def test_policy_probe_is_refused_in_production() -> None:
    app.dependency_overrides[get_settings] = lambda: Settings(environment="production")
    try:
        response = TestClient(app).post(
            "/demo/policy-probe", json=probe_body("restart_service")
        )
    finally:
        app.dependency_overrides.pop(get_settings, None)

    assert response.status_code == 403
