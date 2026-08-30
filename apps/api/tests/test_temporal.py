"""The deterministic temporal layer.

Everything here is timestamp arithmetic, so everything here should be exactly right —
this is the layer that exists precisely so a language model is never asked to notice that
10:04 comes before 10:09. A failure in this file is a defect, not a limitation.

The case that matters most is `test_a_deployment_never_defines_incident_onset`. That bug
appeared twice before M14: in M11 the temporal policy check passed vacuously, and in M13's
live run it printed "deployment preceded incident onset by 0m". Both times the cause was
the same — a candidate cause allowed to define the thing it is supposed to precede.
"""

import json
from datetime import UTC, datetime, timedelta

import pytest

from app.investigation.models import EvidenceItem, EvidenceKind
from app.temporal import (
    CausalCompatibility,
    ObservationType,
    RelationshipType,
    as_utc,
    attribute_deployments,
    build_timeline,
    derive_relationships,
    incident_onset,
    observations_from,
)
from app.temporal.rules import ATTRIBUTION_WINDOW, LOOKBACK, LOOKFORWARD

BASE = datetime(2026, 8, 24, 10, 0, tzinfo=UTC)


def at(minutes: float) -> datetime:
    return BASE + timedelta(minutes=minutes)


def ev(
    kind: EvidenceKind,
    source_id: str,
    when: datetime | None,
    *,
    service: str | None = "svc-auth",
    status: str | None = None,
) -> EvidenceItem:
    return EvidenceItem(
        id=f"{kind.value}:{source_id}",
        kind=kind,
        summary=f"authored {kind.value} {source_id}",
        source_id=source_id,
        provenance="authored test fixture",
        observed_at=when,
        service_id=service,
        attributes={"status": status} if status else {},
    )


def deployment(source_id: str, when: datetime, service: str = "svc-auth") -> EvidenceItem:
    return ev(EvidenceKind.DEPLOYMENT, source_id, when, service=service)


def error(code: str, when: datetime, service: str = "svc-auth") -> EvidenceItem:
    return ev(EvidenceKind.ERROR, code, when, service=service)


def health(when: datetime, status: str, service: str = "svc-auth") -> EvidenceItem:
    return EvidenceItem(
        id=f"health:{service}@{when.isoformat()}",
        kind=EvidenceKind.HEALTH,
        summary=f"{service} health {status}",
        source_id=service,
        provenance="authored test fixture",
        observed_at=when,
        service_id=service,
        attributes={"status": status},
    )


def ticket(source_id: str, when: datetime) -> EvidenceItem:
    return ev(EvidenceKind.TICKET, source_id, when)


# --- time semantics ---------------------------------------------------------------------


def test_naive_datetimes_are_normalised_to_utc() -> None:
    """Fixtures and JSON round-trips produce naive values; comparison would raise."""
    naive = datetime(2026, 8, 24, 10, 0)
    assert as_utc(naive) == BASE
    assert as_utc(naive).tzinfo is UTC


def test_other_zones_are_converted_not_relabelled() -> None:
    from datetime import timezone

    plus_two = datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=2)))
    assert as_utc(plus_two) == BASE


def test_observations_are_ordered_and_ties_break_on_id() -> None:
    evidence = [
        error("ERR_B", at(5)),
        error("ERR_A", at(5)),
        deployment("DEP-1", at(0)),
    ]
    observations = observations_from(evidence)

    assert [o.observed_at for o in observations] == [at(0), at(5), at(5)]
    assert observations[1].id < observations[2].id, "same timestamp resolves on id"


def test_evidence_without_a_timestamp_is_skipped() -> None:
    """A historical precedent from years ago would only pollute the ordering."""
    evidence = [
        deployment("DEP-1", at(0)),
        ev(EvidenceKind.HISTORICAL, "NS-HIST-1", None),
    ]
    assert [o.id for o in observations_from(evidence)] == ["obs:deployment:DEP-1"]


def test_derivation_is_deterministic() -> None:
    evidence = [deployment("DEP-1", at(0)), error("ERR_X", at(5)), ticket("T-1", at(12))]
    first = build_timeline(incident_id="cand-A", evidence=evidence)
    second = build_timeline(incident_id="cand-A", evidence=evidence)
    assert first == second


# --- incident onset -----------------------------------------------------------------------


def test_a_deployment_never_defines_incident_onset() -> None:
    """The regression. A candidate cause that sets onset precedes it by construction.

    Seen twice before M14: M11's temporal check passed with nothing behind it, and M13's
    live run reported "deployment preceded incident onset by 0m".
    """
    evidence = [deployment("DEP-1", at(0)), error("ERR_X", at(9)), ticket("T-1", at(14))]
    onset, basis = incident_onset(observations_from(evidence))

    assert onset is not None
    assert onset.observation_type is ObservationType.ERROR_ONSET
    assert onset.observed_at == at(9), "onset is the first symptom, not the deployment"
    assert "deployments are excluded" in basis

    timeline = build_timeline(incident_id="cand-A", evidence=evidence)
    attribution = timeline.attributions[0]
    assert attribution.seconds_before_onset == 9 * 60, "a real gap, never zero"


def test_onset_is_the_earliest_error_when_it_precedes_reports() -> None:
    evidence = [error("ERR_X", at(5)), health(at(8), "degraded"), ticket("T-1", at(14))]
    onset, basis = incident_onset(observations_from(evidence))
    assert onset.observed_at == at(5)
    assert "error signature onset" in basis


def test_onset_is_health_degradation_when_it_comes_first() -> None:
    evidence = [health(at(3), "degraded"), error("ERR_X", at(7)), ticket("T-1", at(14))]
    onset, basis = incident_onset(observations_from(evidence))
    assert onset.observed_at == at(3)
    assert "health degradation" in basis


def test_onset_falls_back_to_the_first_report() -> None:
    """With no machine signal, the customers are the only symptom available."""
    evidence = [deployment("DEP-1", at(0)), ticket("T-1", at(14))]
    onset, basis = incident_onset(observations_from(evidence))
    assert onset.observation_type is ObservationType.TICKET_REPORT
    assert "first correlated report" in basis


def test_a_healthy_reading_is_not_a_symptom() -> None:
    """A service reading healthy does not start an incident, and neither does recovery."""
    evidence = [health(at(0), "healthy"), health(at(20), "recovering"), ticket("T-1", at(30))]
    onset, _ = incident_onset(observations_from(evidence))
    assert onset.observation_type is ObservationType.TICKET_REPORT


def test_onset_is_undefined_when_nothing_is_a_symptom() -> None:
    onset, basis = incident_onset(observations_from([deployment("DEP-1", at(0))]))
    assert onset is None
    assert "never define onset" in basis


# --- evidence window ----------------------------------------------------------------------


def test_the_window_is_centred_on_onset_and_configured_centrally() -> None:
    evidence = [deployment("DEP-1", at(-5)), error("ERR_X", at(0)), ticket("T-1", at(10))]
    timeline = build_timeline(incident_id="cand-A", evidence=evidence)

    assert timeline.onset_at == at(0)
    assert timeline.window_start == at(0) - LOOKBACK
    assert timeline.window_end == at(0) + LOOKFORWARD
    assert timeline.config_version == "temporal-window-v1"


def test_the_window_is_undefined_without_onset() -> None:
    timeline = build_timeline(incident_id="cand-A", evidence=[deployment("DEP-1", at(0))])
    assert timeline.window_start is None and timeline.window_end is None


# --- relationships -------------------------------------------------------------------------


def relationships_for(evidence):
    observations = observations_from(evidence)
    onset, _ = incident_onset(observations)
    return {r.relationship_type: r for r in derive_relationships(observations, onset)}


def test_a_deployment_before_an_error_is_compatible_with_causality() -> None:
    found = relationships_for([deployment("DEP-1", at(0)), error("ERR_X", at(5))])
    relation = found[RelationshipType.DEPLOYMENT_PRECEDES_ERROR_ONSET]

    assert relation.delta_seconds == 300
    assert relation.compatibility is CausalCompatibility.COMPATIBLE
    assert "preceded" in relation.detail
    assert relation.id == "temporal:deployment_precedes_error_onset:DEP-1:ERR_X"


def test_a_deployment_after_an_error_is_incompatible() -> None:
    """The example-B case. A change cannot have initiated what was already failing."""
    found = relationships_for([error("ERR_X", at(0)), deployment("DEP-1", at(24))])
    relation = found[RelationshipType.DEPLOYMENT_FOLLOWS_ERROR_ONSET]

    assert relation.delta_seconds == -24 * 60
    assert relation.compatibility is CausalCompatibility.INCOMPATIBLE
    assert "cannot have initiated" in relation.detail


def test_a_distant_deployment_is_ordered_correctly_but_not_attributable() -> None:
    found = relationships_for([deployment("DEP-1", at(-120)), error("ERR_X", at(0))])
    relation = found[RelationshipType.DEPLOYMENT_PRECEDES_ERROR_ONSET]

    assert relation.compatibility is CausalCompatibility.TOO_DISTANT
    assert "attribution window" in relation.detail


def test_near_simultaneous_events_are_not_treated_as_ordered() -> None:
    """Clock skew and coarse observation intervals are not causal sequences."""
    found = relationships_for(
        [deployment("DEP-1", at(0)), error("ERR_X", BASE + timedelta(seconds=20))]
    )
    relation = found[RelationshipType.DEPLOYMENT_PRECEDES_ERROR_ONSET]
    assert relation.compatibility is CausalCompatibility.NOT_APPLICABLE


def test_deployment_and_health_degradation_are_related_both_ways() -> None:
    after = relationships_for([deployment("DEP-1", at(0)), health(at(7), "degraded")])
    assert (
        after[RelationshipType.DEPLOYMENT_PRECEDES_HEALTH_DEGRADATION].delta_seconds
        == 420
    )

    before = relationships_for([health(at(0), "degraded"), deployment("DEP-1", at(10))])
    relation = before[RelationshipType.DEPLOYMENT_FOLLOWS_HEALTH_DEGRADATION]
    assert relation.compatibility is CausalCompatibility.INCOMPATIBLE


def test_machine_symptoms_versus_first_report_is_not_a_causal_claim() -> None:
    """Useful operationally — did monitoring see it first — but not about causation."""
    found = relationships_for([error("ERR_X", at(0)), ticket("T-1", at(5))])
    relation = found[RelationshipType.ERROR_PRECEDES_FIRST_REPORT]

    assert relation.delta_seconds == 300
    assert relation.compatibility is CausalCompatibility.NOT_APPLICABLE


def test_relationships_do_not_explode_quadratically() -> None:
    """Only comparisons the product asks about are derived."""
    evidence = [
        deployment("DEP-1", at(0)),
        error("E1", at(3)),
        error("E2", at(4)),
        health(at(5), "degraded"),
        health(at(9), "critical"),
        ticket("T-1", at(12)),
        ticket("T-2", at(14)),
        ticket("T-3", at(16)),
    ]
    observations = observations_from(evidence)
    onset, _ = incident_onset(observations)
    derived = derive_relationships(observations, onset)

    # 1 deployment x (2 errors + 2 degradations) + 2 errors + 2 degradations vs one report.
    assert len(derived) == 8
    assert len(derived) < len(observations) ** 2


def test_the_onset_relationship_is_not_emitted_twice() -> None:
    """Onset is usually the first error; saying it twice is the same fact reworded."""
    evidence = [deployment("DEP-1", at(0)), error("ERR_X", at(5))]
    derived = derive_relationships(
        observations_from(evidence), incident_onset(observations_from(evidence))[0]
    )
    assert len(derived) == 1
    assert RelationshipType.DEPLOYMENT_PRECEDES_INCIDENT_ONSET not in {
        r.relationship_type for r in derived
    }


# --- deployment attribution ------------------------------------------------------------------


def attribution_for(evidence):
    observations = observations_from(evidence)
    onset, _ = incident_onset(observations)
    relationships = derive_relationships(observations, onset)
    return attribute_deployments(observations, onset, relationships)


def test_a_deployment_shortly_before_onset_is_temporally_plausible() -> None:
    result = attribution_for(
        [health(at(-10), "healthy"), deployment("DEP-1", at(0)), error("ERR_X", at(5))]
    )[0]

    assert result.temporally_plausible is True
    assert result.seconds_before_onset == 300
    assert result.compatibility is CausalCompatibility.COMPATIBLE
    assert result.supporting_evidence_ids
    assert not result.contradicting_evidence_ids
    # It says "consistent with", never "caused".
    assert "not the same as evidence that it did" in result.detail
    assert "caused" not in result.detail


def test_a_deployment_after_onset_is_rejected_as_the_initiating_cause() -> None:
    result = attribution_for([error("ERR_X", at(0)), deployment("DEP-1", at(24))])[0]

    assert result.temporally_plausible is False
    assert result.seconds_before_onset == -24 * 60
    assert result.compatibility is CausalCompatibility.INCOMPATIBLE
    assert "error:ERR_X" in result.contradicting_evidence_ids


def test_a_stale_deployment_is_rejected() -> None:
    result = attribution_for([deployment("DEP-1", at(-240)), error("ERR_X", at(0))])[0]

    assert result.temporally_plausible is False
    assert result.compatibility is CausalCompatibility.TOO_DISTANT
    assert result.seconds_before_onset == 240 * 60


def test_a_symptom_predating_the_deployment_contradicts_it() -> None:
    """Even with onset arithmetic that would otherwise pass."""
    result = attribution_for(
        [
            health(at(-15), "degraded"),
            deployment("DEP-1", at(0)),
            error("ERR_X", at(5)),
        ]
    )[0]

    assert result.temporally_plausible is False
    assert result.contradicting_evidence_ids


def test_multiple_deployments_are_judged_separately() -> None:
    results = {
        entry.deployment_id: entry
        for entry in attribution_for(
            [
                deployment("DEP-OLD", at(-180)),
                deployment("DEP-NEW", at(-4)),
                error("ERR_X", at(0)),
            ]
        )
    }

    assert results["DEP-NEW"].temporally_plausible is True
    assert results["DEP-OLD"].temporally_plausible is False
    assert results["DEP-OLD"].compatibility is CausalCompatibility.TOO_DISTANT


def test_attribution_is_undefined_without_onset() -> None:
    result = attribution_for([deployment("DEP-1", at(0))])[0]
    assert result.temporally_plausible is False
    assert "cannot be placed relative to it" in result.detail


def test_the_attribution_window_is_the_configured_one() -> None:
    inside = attribution_for(
        [deployment("DEP-1", at(0)), error("ERR_X", at(ATTRIBUTION_WINDOW.total_seconds() / 60 - 1))]
    )[0]
    outside = attribution_for(
        [deployment("DEP-1", at(0)), error("ERR_X", at(ATTRIBUTION_WINDOW.total_seconds() / 60 + 1))]
    )[0]

    assert inside.temporally_plausible is True
    assert outside.temporally_plausible is False


# --- the two worked examples from the brief ---------------------------------------------------


def test_example_a_supports_the_deployment_as_a_candidate() -> None:
    """healthy → deploy → error → degrade → report."""
    timeline = build_timeline(
        incident_id="cand-A",
        evidence=[
            health(at(-6), "healthy"),
            deployment("DEP-1", at(4)),
            error("ERR_AUTH_STALL", at(9)),
            health(at(11), "degraded"),
            ticket("T-1", at(14)),
        ],
    )

    assert timeline.onset_at == at(9)
    assert timeline.attributions[0].temporally_plausible is True
    assert timeline.attributions[0].seconds_before_onset == 300


def test_example_b_rules_the_deployment_out() -> None:
    """error → degrade → deploy → report. Same current state, opposite conclusion."""
    timeline = build_timeline(
        incident_id="cand-B",
        evidence=[
            error("ERR_AUTH_STALL", at(-20)),
            health(at(-17), "degraded"),
            deployment("DEP-1", at(4)),
            ticket("T-1", at(14)),
        ],
    )

    assert timeline.onset_at == at(-20)
    attribution = timeline.attributions[0]
    assert attribution.temporally_plausible is False
    assert attribution.compatibility is CausalCompatibility.INCOMPATIBLE
    assert len(attribution.contradicting_evidence_ids) == 2


def test_the_two_examples_are_distinguishable() -> None:
    """The point of the milestone: identical current state, different chronology."""
    common = {"health_now": "degraded", "deployment": "DEP-1", "error": "ERR_AUTH_STALL"}
    assert common  # both cases end in the same state

    a = build_timeline(
        incident_id="A",
        evidence=[deployment("DEP-1", at(4)), error("ERR_AUTH_STALL", at(9)), health(at(11), "degraded")],
    )
    b = build_timeline(
        incident_id="B",
        evidence=[error("ERR_AUTH_STALL", at(-20)), health(at(-17), "degraded"), deployment("DEP-1", at(4))],
    )

    assert a.attributions[0].temporally_plausible != b.attributions[0].temporally_plausible


# --- evidence registry integration --------------------------------------------------------------


def test_temporal_facts_become_citable_evidence() -> None:
    from app.investigation.evidence import temporal_evidence

    evidence = [health(at(-6), "healthy"), deployment("DEP-1", at(0)), error("ERR_X", at(5))]
    derived = temporal_evidence(incident_id="cand-A", evidence=evidence)

    ids = {item.id for item in derived}
    assert "temporal:onset:cand-A" in ids
    assert "temporal:attribution:DEP-1" in ids
    assert any(item.id.startswith("temporal:deployment_precedes_error_onset") for item in derived)
    assert all(item.kind is EvidenceKind.TEMPORAL for item in derived)
    assert all(
        item.provenance == "IncidentIQ deterministic temporal analysis" for item in derived
    )


def test_temporal_evidence_ids_are_stable_across_runs() -> None:
    from app.investigation.evidence import temporal_evidence

    evidence = [deployment("DEP-1", at(0)), error("ERR_X", at(5))]
    first = [item.id for item in temporal_evidence(incident_id="c", evidence=evidence)]
    second = [item.id for item in temporal_evidence(incident_id="c", evidence=evidence)]
    assert first == second


@pytest.mark.parametrize("minutes,expected", [(5, "5m"), (0.5, "30s"), (120, "2.0h")])
def test_gaps_are_rendered_readably(minutes: float, expected: str) -> None:
    from app.temporal.timeline import _humanise

    assert _humanise(int(minutes * 60)) == expected


# --- persistence and eval versioning ------------------------------------------------------


def test_the_evidence_schema_is_versioned_separately_from_the_prompt() -> None:
    """M14 changed what the model sees without changing a word of the prompt.

    Conflating "the evidence improved" with "the prompt improved" would make both
    unmeasurable, which is the whole reason these are two version strings.
    """
    from app.investigation.rules import (
        CURRENT_EVIDENCE_SCHEMA,
        EVIDENCE_SCHEMA_V1,
        EVIDENCE_SCHEMA_V2,
    )
    from app.investigation.prompt_v2 import SYSTEM_PROMPT_V2

    assert EVIDENCE_SCHEMA_V1 == "evidence-v1"
    assert CURRENT_EVIDENCE_SCHEMA == EVIDENCE_SCHEMA_V2 == "evidence-v2"
    # The v2 prompt is untouched by this milestone.
    assert "A. DIAGNOSIS" in SYSTEM_PROMPT_V2


def test_the_v1_prompt_is_still_frozen_after_the_evidence_change() -> None:
    import hashlib

    from app.investigation import SYSTEM_PROMPT

    assert (
        hashlib.sha256(SYSTEM_PROMPT.encode()).hexdigest()
        == "2089efccbc3d5a130d04ea97205b02584cc8ca654dabf1c4dc4d39a3a85b5c23"
    )


def test_temporal_evidence_survives_a_snapshot_round_trip() -> None:
    """The M13 guarantee has to hold for derived evidence too."""
    from app.investigation.evidence import temporal_evidence

    derived = temporal_evidence(
        incident_id="cand-A",
        evidence=[deployment("DEP-1", at(0)), error("ERR_X", at(5))],
    )
    restored = [
        EvidenceItem.model_validate(item.model_dump(mode="json")) for item in derived
    ]
    assert restored == derived
    assert all(item.attributes for item in restored)


def test_evidence_recorded_before_m14_still_validates() -> None:
    """Old snapshots have no service_id or attributes. They must still load."""
    legacy = {
        "id": "deployment:DEP-2041",
        "kind": "deployment",
        "summary": "svc-auth version 4.12.0 deployed 18 minutes before the first report",
        "source_id": "DEP-2041",
        "provenance": "Northstar Cloud synthetic operations fixture",
        "observed_at": "2026-08-24T08:52:00Z",
    }
    item = EvidenceItem.model_validate(legacy)
    assert item.service_id is None and item.attributes == {}


def test_eval_versions_are_separate_files_and_older_ones_are_untouched() -> None:
    import json

    from app.config import get_settings
    from evaluation.investigation import EVAL_FILES, load_cases, load_labels

    base = get_settings().investigation_evals_dir
    assert set(EVAL_FILES) == {"v1", "v2", "v3"}

    v2 = {case["id"]: case for case in load_cases(base, eval_version="v2")}
    v3 = {case["id"]: case for case in load_cases(base, eval_version="v3")}

    # v3 adds cases and adds operations to two of them; it edits nothing else.
    assert set(v2) < set(v3)
    for case_id, case in v2.items():
        if case_id in ("IV04", "IV12"):
            continue
        assert v3[case_id] == case, case_id

    # v1 is untouched by everything.
    v1 = load_cases(base, eval_version="v1")
    assert len(v1) == 16
    payload = json.loads(
        (base / "investigation_cases_v3.json").read_text(encoding="utf-8")
    )
    assert payload["eval_version"] == "investigation-eval-v3"
    assert payload["evidence_schema"] == "evidence-v2"

    labels = load_labels(base, eval_version="v3")
    assert "TC01" in labels and "IV17" in labels


def test_iv04_and_iv12_now_carry_materially_different_evidence() -> None:
    """The central acceptance case, checked at the data level.

    They were indistinguishable because evidence collection is service-scoped and both are
    svc-connector: identical operational signals however differently their tickets read.
    No label change could fix that — the evidence had to differ, and now does.
    """
    from app.config import get_settings
    from evaluation.investigation import load_cases

    cases = {
        case["id"]: case
        for case in load_cases(get_settings().investigation_evals_dir, eval_version="v3")
    }
    iv04, iv12 = cases["IV04"], cases["IV12"]

    assert iv04["service_id"] == iv12["service_id"] == "svc-connector"
    assert "operations" in iv04 and "operations" in iv12

    iv04_errors = {row["code"] for row in iv04["operations"]["errors"]}
    iv12_errors = {row["code"] for row in iv12["operations"]["errors"]}
    assert iv04_errors.isdisjoint(iv12_errors), "different failure mechanisms"

    # IV04 has a change inside the window; IV12's only release is hours earlier.
    assert iv04["operations"]["deployments"][0]["deployed_at"] > "2026-08-25T12:00"
    assert iv12["operations"]["deployments"][0]["deployed_at"] < "2026-08-25T06:00"

    # And neither block says which action is right.
    for case in (iv04, iv12):
        blob = json.dumps(case["operations"]).lower()
        for leak in ("restart", "rollback", "roll back", "should", "correct action"):
            assert leak not in blob, f"{case['id']} leaks the expected action: {leak}"


def test_temporal_cases_do_not_reveal_their_expected_action() -> None:
    from app.config import get_settings
    from evaluation.investigation import load_cases

    cases = [
        case
        for case in load_cases(get_settings().investigation_evals_dir, eval_version="v3")
        if case["id"].startswith("TC")
    ]
    assert len(cases) == 8

    for case in cases:
        blob = json.dumps({"tickets": case["tickets"], "operations": case["operations"]})
        for leak in ("restart", "rollback", "roll back", "redeploy", "should"):
            assert leak not in blob.lower(), f"{case['id']} leaks: {leak}"


def test_deployment_attribution_grading_is_conservative() -> None:
    """The grader reads structured output only — citations and the action type.

    Keyword matching on the hypothesis text was tried first and scored "no release
    involved" as blaming a release. Negation is exactly what keyword matching cannot do,
    so the grader reads evidence ids instead, which are exact.
    """
    from evaluation.investigation import _attribution_correct
    from tests.test_investigation import hypothesis, output

    blames = output(
        hypotheses=(
            hypothesis("Regression from the release", supporting=("deployment:DEP-1",)),
        )
    )
    does_not = output(
        hypotheses=(
            hypothesis(
                "Stalled sync workers, no release involved",
                supporting=("error:ERR_SYNC_STALLED",),
            ),
        )
    )

    assert _attribution_correct("deployment_plausible", blames) is True
    assert _attribution_correct("deployment_plausible", does_not) is False
    assert _attribution_correct("deployment_implausible", blames) is False
    assert _attribution_correct("deployment_implausible", does_not) is True
    assert _attribution_correct("no_deployment", does_not) is True
    # An unknown expectation never fails a case it was not written for.
    assert _attribution_correct("something_else", blames) is True


def test_temporal_ids_stay_short_enough_to_cite_exactly() -> None:
    """The defect the eval-v3 run exposed.

    Relationship ids were composed from two full evidence ids. A health evidence id embeds
    an ISO timestamp — colons inside a colon-delimited id — which produced 111-character
    strings, and the model truncated one. Validation rejected it, which is the guardrail
    working; but an id that cannot be copied exactly is a bad id regardless.
    """
    from app.investigation.evidence import temporal_evidence

    evidence = [
        deployment("DEP-2041", at(0)),
        error("ERR_SAML_INVALID_ASSERTION", at(3)),
        health(at(18), "degraded", service="svc-analytics"),
        ticket("TCT-121", at(20)),
    ]
    derived = temporal_evidence(incident_id="cand-TKT-4101", evidence=evidence)

    for item in derived:
        assert len(item.id) <= 80, f"{item.id} is {len(item.id)} characters"
        # No ISO timestamp smuggled into a colon-delimited id.
        assert "+00:00" not in item.id
        assert item.id.count(":") <= 4

    # Still unique, which is what the timestamp was there for.
    assert len({item.id for item in derived}) == len(derived)


def test_two_health_observations_on_one_service_do_not_collide() -> None:
    from app.investigation.evidence import temporal_evidence

    derived = temporal_evidence(
        incident_id="c",
        evidence=[
            deployment("DEP-1", at(0)),
            health(at(10), "degraded"),
            health(at(25), "critical"),
        ],
    )
    assert len({item.id for item in derived}) == len(derived)
