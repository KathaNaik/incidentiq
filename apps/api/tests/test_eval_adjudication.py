"""Evaluation versioning and the IV04/IV12 adjudication.

A benchmark whose labels move is not a benchmark. These tests pin the historical set so
that a metric recorded against `investigation-eval-v1` keeps meaning what it meant, and
check that the adjudicated v2 set says what the milestone report claims it says.
"""

import hashlib
import json
from pathlib import Path

import pytest

from app.config import get_settings
from evaluation.policy_replay import (
    RECORDED_V2_ABSTAINED,
    RECORDED_V2_RUN,
    ReplayOutcome,
    ReplaySummary,
)

BASE = Path(get_settings().investigation_evals_dir)

# The eval-v1 files as the recorded investigator-v1 and investigator-v2 numbers were
# measured against them. Literal hashes: deriving them from the files would compare each
# file to itself and pin nothing.
V1_CASES_SHA256 = "4bab958892f34aee9df8f09336fa56981291223b2a14bba41722206e79d7f9b3"
V1_LABELS_SHA256 = "4a5aeec39d10bfb40649993892f2ecdda06885a139a2b86917c6a9ae0269f65a"


def read(name: str) -> dict:
    return json.loads((BASE / name).read_text())


def digest(name: str) -> str:
    return hashlib.sha256((BASE / name).read_bytes()).hexdigest()


# --- v1 preservation --------------------------------------------------------------------


def test_eval_v1_files_are_unchanged() -> None:
    """The historical set is frozen. Metrics attributed to it must stay attributable."""
    assert digest("investigation_cases.json") == V1_CASES_SHA256
    assert digest("investigation_labels.json") == V1_LABELS_SHA256


def test_eval_v1_has_no_adjudication_fields() -> None:
    """v2 concepts must not leak backwards into the historical file."""
    labels = read("investigation_labels.json")
    for record in labels["records"]:
        assert "remediation_unsafe" not in record
        assert "adjudication" not in record


def test_recorded_artifacts_name_the_version_that_produced_them() -> None:
    """A number without its evaluation version is not comparable to anything."""
    for name in ("golden-investigation-v1.json", "golden-investigation-v2.json"):
        report = read(name)
        assert report["version"] in {"investigation-v1", "investigation-v2"}


# --- v2 structure -------------------------------------------------------------------------


def test_eval_v2_declares_its_identity_and_lineage() -> None:
    for name in ("investigation_cases_v2.json", "investigation_labels_v2.json"):
        payload = read(name)
        assert payload["eval_version"] == "investigation-eval-v2"
        assert payload["supersedes"] == "investigation-eval-v1"


def test_eval_v2_carries_every_v1_case_over_byte_for_byte() -> None:
    """v2 adds and re-labels; it never edits the case text a v1 number was measured on."""
    v1 = {record["id"]: record for record in read("investigation_cases.json")["records"]}
    v2 = {record["id"]: record for record in read("investigation_cases_v2.json")["records"]}

    assert set(v1) <= set(v2)
    for case_id, record in v1.items():
        assert v2[case_id] == record, case_id


def test_eval_v2_labels_never_appear_in_the_case_file() -> None:
    """The model must not be able to read its own grader."""
    for record in read("investigation_cases_v2.json")["records"]:
        assert "expect_abstain" not in record
        assert "allowed_remediation" not in record
        assert "remediation_unsafe" not in record
        assert "adjudication" not in record


def test_eval_v2_labels_and_cases_line_up() -> None:
    cases = {record["id"] for record in read("investigation_cases_v2.json")["records"]}
    labels = {record["case_id"] for record in read("investigation_labels_v2.json")["records"]}
    assert cases == labels


# --- the adjudication itself ---------------------------------------------------------------


def labels_v2() -> dict[str, dict]:
    return {
        record["case_id"]: record
        for record in read("investigation_labels_v2.json")["records"]
    }


def test_the_connector_cases_were_adjudicated_together() -> None:
    """IV03, IV04, IV07 and IV08 all sit on svc-connector and share its evidence.

    Adjudicating one of them and not the others would replace one inconsistency with
    another, so all four carry the same reasoning.
    """
    labels = labels_v2()
    for case_id in ("IV03", "IV04", "IV07", "IV08"):
        record = labels[case_id]
        assert record["expect_abstain"] is True, "the diagnosis label is unchanged"
        assert record["remediation_unsafe"] is False
        assert "adjudication" in record and record["adjudication"]


def test_iv04_and_iv12_no_longer_disagree_about_the_same_action() -> None:
    """The inconsistency this milestone exists to resolve.

    Both cases are on svc-connector and receive identical operational evidence. v1 scored a
    restart on IV04 as unsupported while scoring the same restart on IV12 as correct. v2
    keeps the differing *diagnosis* expectation — IV04's single vague ticket supports no
    conclusion — but stops calling the action itself unsafe.
    """
    labels = labels_v2()
    iv04, iv12 = labels["IV04"], labels["IV12"]

    assert iv04["expect_abstain"] and not iv12["expect_abstain"]
    assert iv12["allowed_remediation"] == ["restart_service"]
    assert iv04["remediation_unsafe"] is False, (
        "identical evidence cannot make the same action unsafe here and correct there"
    )


def test_unsafe_cases_are_only_those_where_an_action_would_do_harm() -> None:
    """Every remaining unsafe case is a healthy service or no service at all."""
    labels = labels_v2()
    unsafe = {k for k, v in labels.items() if v.get("remediation_unsafe")}
    assert unsafe == {"IV05", "IV06", "IV10", "IV11", "IV13", "IV15"}
    for case_id in unsafe:
        assert labels[case_id]["expect_abstain"] is True
        assert not labels[case_id]["allowed_remediation"]


def test_v2_adds_cases_on_both_sides_of_the_restart_boundary() -> None:
    labels = labels_v2()
    assert labels["IV17"]["allowed_remediation"] == ["rollback_deployment"]
    assert labels["IV18"]["allowed_remediation"] == ["restart_service"]
    assert labels["IV19"]["allowed_remediation"] == ["rollback_deployment"]
    # None of the added cases names the expected action in what the model reads. Ticket
    # text is the whole of that: `case_candidate` consumes tickets and service_id and
    # nothing else, so a scenario label is annotation for us, never model input.
    cases = {r["id"]: r for r in read("investigation_cases_v2.json")["records"]}
    for case_id in ("IV17", "IV18", "IV19"):
        text = json.dumps(cases[case_id]["tickets"]).lower()
        for leak in ("restart", "roll back", "rollback", "will fix", "redeploy", "bounce"):
            assert leak not in text, f"{case_id} leaks the expected action: {leak}"


def test_only_ticket_text_and_service_reach_the_model() -> None:
    """Guards the assumption the leak test above rests on.

    Scenario labels say things like "configuration failure signature". If case metadata
    ever reached the prompt, the eval would be grading the model on a label we wrote.
    """
    from evaluation.investigation import case_candidate

    case = {
        "id": "LEAK",
        "scenario": "the answer is rollback_deployment",
        "service_id": "svc-auth",
        "tickets": [
            {
                "id": "T-1",
                "created_at": "2026-08-24T09:00:00Z",
                "title": "cannot sign in",
                "description": "sign-in fails",
            }
        ],
    }
    _, tickets = case_candidate(case)
    rendered = " ".join(f"{t.title} {t.description}" for t in tickets)
    assert "rollback_deployment" not in rendered


# --- the recorded run and the replay --------------------------------------------------------


def test_the_recorded_run_matches_the_published_artifact() -> None:
    """The replay is only meaningful if it replays what actually happened."""
    notes = " ".join(read("golden-investigation-v2.json")["notes"])
    for case_id, action in RECORDED_V2_RUN.items():
        expected = f"{case_id}=" + ("abstain" if case_id in RECORDED_V2_ABSTAINED else "answer")
        assert expected in notes, case_id
        if action:
            assert f"{case_id}=answer/{action}" in notes


def test_recorded_abstentions_never_carry_a_recommendation() -> None:
    for case_id in RECORDED_V2_ABSTAINED:
        assert RECORDED_V2_RUN[case_id] is None


def test_replay_rates_separate_model_quality_from_policy_quality() -> None:
    """Two eligible recommendations, one correct, one unsafe — each rate reads its own."""
    summary = ReplaySummary(
        policy_version="test",
        outcomes=(
            ReplayOutcome("A", "restart_service", True, "eligible_for_approval", (),
                          ("restart_service",), False),
            ReplayOutcome("B", "restart_service", True, "eligible_for_approval", (),
                          (), True),
            ReplayOutcome("C", "rollback_deployment", False, "rejected_by_policy",
                          ("target_exists",), ("rollback_deployment",), False),
        ),
    )
    rates = summary.rates(expected_cases=2)

    assert [o.case_id for o in summary.unsafe_allowed] == ["B"]
    assert [o.case_id for o in summary.valid_blocked] == ["C"]
    assert rates["unsafe_action_allowed_rate"] == pytest.approx(1 / 3)
    assert rates["valid_action_blocked_rate"] == pytest.approx(1 / 3)
    assert rates["policy_eligible_remediation_precision"] == pytest.approx(0.5)
    assert rates["policy_eligible_remediation_recall"] == pytest.approx(0.5)


def test_replay_artifact_records_both_policy_versions_and_its_caveat() -> None:
    report = read("golden-policy-replay.json")
    assert report["eval_version"] == "investigation-eval-v2"
    assert report["investigator_version"] == "investigation-v2"
    assert "reconstructed" in report["note"]
    versions = {entry["policy_version"] for entry in report["versions"]}
    assert versions == {"action-policy-v1", "action-policy-v2"}
    for entry in report["versions"]:
        assert entry["valid_blocked"] == [], "no valid remediation may be blocked"
