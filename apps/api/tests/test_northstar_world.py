"""The authored Northstar world, checked against its frozen design.

`docs/NORTHSTAR_WORLD_V2.md` is the ground truth these assert. They do not check that
correlation *finds* the right groupings — that is an observation, recorded separately in
the world-v2 runtime regression and deliberately not something a fixture may be edited to
satisfy. What they check is that the authored world says what the design says it says.

The chronology tests matter most. A deployment that drifts to the wrong side of a health
observation silently destroys the causal shape the incident exists to demonstrate, and
nothing else in the suite would notice.
"""

import json
from datetime import datetime
from pathlib import Path

import pytest

from app.config import get_settings

FIXTURES = get_settings().fixtures_dir


def load(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def world():
    return {
        "services": load("services.json")["records"],
        "tickets": load("tickets.json")["records"],
        "incidents": load("incidents.json")["records"],
        "links": load("incident_tickets.json")["records"],
        "ops": load("operations.json"),
    }


def when(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- integrity --------------------------------------------------------------------------


def test_ids_are_unique(world) -> None:
    for kind in ("services", "tickets", "incidents"):
        ids = [r["id"] for r in world[kind]]
        assert len(ids) == len(set(ids)), f"duplicate id in {kind}"
    for kind in ("deployments",):
        ids = [r["id"] for r in world["ops"][kind]]
        assert len(ids) == len(set(ids))


def test_every_service_reference_resolves(world) -> None:
    known = {s["id"] for s in world["services"]}
    for ticket in world["tickets"]:
        # `service_id` is genuinely optional: a report where the reporter named no service
        # is a real state the product handles, and some authored tickets omit the key.
        if ticket.get("service_id") is not None:
            assert ticket["service_id"] in known, ticket["id"]
    for incident in world["incidents"]:
        for service in incident["affected_service_ids"]:
            assert service in known, incident["id"]
    for kind in ("deployments", "health", "errors"):
        for record in world["ops"][kind]:
            assert record["service_id"] in known, record


def test_declared_links_reference_real_records(world) -> None:
    tickets = {t["id"] for t in world["tickets"]}
    incidents = {i["id"] for i in world["incidents"]}
    for link in world["links"]:
        assert link["ticket_id"] in tickets, link
        assert link["incident_id"] in incidents, link


def test_every_service_has_an_operational_role(world) -> None:
    """No service exists only to raise the count."""
    used = {t.get("service_id") for t in world["tickets"] if t.get("service_id")}
    for service in world["services"]:
        assert service["id"] in used, f"{service['id']} appears in no ticket"


def test_timestamps_are_coherent(world) -> None:
    for ticket in world["tickets"]:
        assert ticket["created_at"].endswith("Z")
        when(ticket["created_at"])  # parses
    for record in world["ops"]["errors"]:
        assert when(record["first_seen"]) <= when(record["last_seen"]), record["code"]


def test_the_world_is_authored_not_imported(world) -> None:
    """Provenance guard: Northstar is original work, never relabelled external data.

    The external corpora carry injected synthetic PII and a distinctive record shape. If
    any of those fields appear here, something was copied that should not have been.
    """
    foreign = {"record_type", "correspondence", "diagnostics_summary", "source_id"}
    for ticket in world["tickets"]:
        assert not (foreign & set(ticket)), ticket["id"]
    assert load("tickets.json")["dataset"] == "northstar-cloud"
    assert load("tickets.json")["synthetic"] is True


# --- the frozen hero --------------------------------------------------------------------

HERO_TICKETS = {
    "TKT-4101": "2026-08-24T09:08:00Z",
    "TKT-4102": "2026-08-24T09:14:00Z",
    "TKT-4103": "2026-08-24T09:19:00Z",
    "TKT-4104": "2026-08-24T09:31:00Z",
    "TKT-4105": "2026-08-24T09:44:00Z",
}


def test_hero_tickets_are_untouched(world) -> None:
    by_id = {t["id"]: t for t in world["tickets"]}
    for ticket_id, created in HERO_TICKETS.items():
        assert by_id[ticket_id]["created_at"] == created
        assert by_id[ticket_id]["service_id"] == "svc-auth"


def test_hero_deployment_and_health_are_untouched(world) -> None:
    deployment = next(d for d in world["ops"]["deployments"] if d["id"] == "DEP-2041")
    assert deployment["deployed_at"] == "2026-08-24T08:52:00Z"
    assert deployment["service_id"] == "svc-auth"
    assert deployment["version"] == "4.12.0"

    hero_health = {
        (h["observed_at"], h["status"])
        for h in world["ops"]["health"]
        if h["service_id"] == "svc-auth" and h["observed_at"].startswith("2026-08-24")
    }
    assert hero_health == {
        ("2026-08-24T08:40:00Z", "healthy"),
        ("2026-08-24T09:10:00Z", "degraded"),
        ("2026-08-24T09:25:00Z", "critical"),
    }


def test_hero_membership_is_untouched(world) -> None:
    members = {l["ticket_id"] for l in world["links"] if l["incident_id"] == "INC-1042"}
    assert members == set(HERO_TICKETS)


def test_connector_incident_is_untouched(world) -> None:
    members = {l["ticket_id"] for l in world["links"] if l["incident_id"] == "INC-1043"}
    assert members == {"TKT-4111", "TKT-4112", "TKT-4113"}
    assert any(e["code"] == "ERR_SYNC_STALLED" for e in world["ops"]["errors"])


# --- the incident stories ---------------------------------------------------------------

#: Every incident the design declares, with the causal shape it exists to demonstrate.
STORIES = {
    "INC-1044": ("svc-auth", 5, None),
    "INC-1045": ("svc-analytics", 4, None),
    "INC-1046": ("svc-analytics", 4, None),
    "INC-1047": ("svc-billing", 4, None),
    "INC-1048": ("svc-api", 4, "DEP-2047"),
    "INC-1049": ("svc-notifications", 4, None),
    "INC-1050": ("svc-search", 4, "DEP-2048"),
    "INC-1051": ("svc-files", 4, None),
}


@pytest.mark.parametrize(("incident_id", "spec"), STORIES.items())
def test_each_incident_has_its_declared_reports(world, incident_id, spec) -> None:
    service, count, _ = spec
    by_id = {t["id"]: t for t in world["tickets"]}
    members = [l["ticket_id"] for l in world["links"] if l["incident_id"] == incident_id]

    assert len(members) == count
    for ticket_id in members:
        assert by_id[ticket_id]["service_id"] == service


@pytest.mark.parametrize(("incident_id", "spec"), STORIES.items())
def test_reports_stay_inside_the_linking_regime(world, incident_id, spec) -> None:
    """Consecutive reports ≤ 40 minutes apart, per the design.

    Not a claim that correlation will group them — a claim that the world does not depend
    on threshold-edge behaviour to make its ground truth legible.
    """
    by_id = {t["id"]: t for t in world["tickets"]}
    members = sorted(
        (l["ticket_id"] for l in world["links"] if l["incident_id"] == incident_id),
        key=lambda i: by_id[i]["created_at"],
    )
    times = [when(by_id[i]["created_at"]) for i in members]
    gaps = [(b - a).total_seconds() / 60 for a, b in zip(times, times[1:], strict=False)]
    assert all(gap <= 40 for gap in gaps), f"{incident_id} gaps: {gaps}"


def test_no_deployment_incidents_really_have_none(world) -> None:
    """The four external-dependency and backlog incidents must have no deployment.

    If one crept into the attribution window, the incident would quietly become another
    rollback story and the world would stop demonstrating that not every failure ships.
    """
    incidents = {i["id"]: i for i in world["incidents"]}
    for incident_id, (service, _, deployment) in STORIES.items():
        if deployment is not None:
            continue
        onset = when(incidents[incident_id]["detected_at"])
        for record in world["ops"]["deployments"]:
            if record["service_id"] != service:
                continue
            gap = (onset - when(record["deployed_at"])).total_seconds() / 60
            assert not (0 <= gap <= 60), (
                f"{incident_id} is designed as no-deployment but {record['id']} "
                f"shipped {gap:.0f} min before onset"
            )


def test_api_incident_is_a_clean_deployment_attribution(world) -> None:
    """Healthy → deploy → errors → degraded. The deployment is plausible as the cause."""
    deploy = when(
        next(d for d in world["ops"]["deployments"] if d["id"] == "DEP-2047")["deployed_at"]
    )
    errors = when(
        next(e for e in world["ops"]["errors"] if e["code"] == "ERR_API_5XX_SPIKE")[
            "first_seen"
        ]
    )
    health = sorted(
        (h for h in world["ops"]["health"] if h["service_id"] == "svc-api"),
        key=lambda h: h["observed_at"],
    )
    healthy_before = [h for h in health if when(h["observed_at"]) < deploy]
    degraded_after = [
        h for h in health if when(h["observed_at"]) > deploy and h["status"] != "healthy"
    ]

    assert healthy_before and all(h["status"] == "healthy" for h in healthy_before)
    assert deploy < errors
    assert degraded_after


def test_search_incident_is_the_deployment_after_symptoms_counterexample(world) -> None:
    """Errors → degraded → deploy. The deployment cannot be the initiating cause.

    This is the case policy-v2 must refuse to support a rollback for, and it must refuse
    on the evidence — the service was already unhealthy before the change shipped.
    """
    deploy = when(
        next(d for d in world["ops"]["deployments"] if d["id"] == "DEP-2048")["deployed_at"]
    )
    errors = when(
        next(e for e in world["ops"]["errors"] if e["code"] == "ERR_INDEX_BACKLOG")[
            "first_seen"
        ]
    )
    degraded_before = [
        h
        for h in world["ops"]["health"]
        if h["service_id"] == "svc-search"
        and h["status"] != "healthy"
        and when(h["observed_at"]) < deploy
    ]

    assert errors < deploy, "errors must precede the deployment"
    assert degraded_before, "the service must already be degraded before the deployment"


def test_health_is_recorded_as_sequences(world) -> None:
    """Temporal reasoning needs a before as well as an after."""
    from collections import defaultdict

    per_service = defaultdict(list)
    for record in world["ops"]["health"]:
        per_service[record["service_id"]].append(record)

    for service, _, _ in STORIES.values():
        observations = per_service[service]
        assert len(observations) >= 3, f"{service} has no health sequence"
        assert any(o["status"] == "healthy" for o in observations)
        assert any(o["status"] != "healthy" for o in observations)


def test_some_deployments_cause_nothing(world) -> None:
    """Without unrelated changes, temporal attribution never has to reject a candidate."""
    implicated = {"DEP-2041", "DEP-2047"}
    unrelated = [d for d in world["ops"]["deployments"] if d["id"] not in implicated]
    assert len(unrelated) >= 4


# --- noise and boundary cases -----------------------------------------------------------

ISOLATED = [f"TKT-43{n:02d}" for n in range(1, 15)]
BOUNDARY = [f"TKT-44{n:02d}" for n in range(1, 11)]


def test_isolated_reports_are_declared_to_no_incident(world) -> None:
    declared = {l["ticket_id"] for l in world["links"]}
    for ticket_id in ISOLATED:
        assert ticket_id not in declared, f"{ticket_id} is support traffic, not an incident"


def test_boundary_reports_are_not_pre_declared(world) -> None:
    """Their truth lives in the design document, and the queue must ask about them.

    Declaring them here would hand correlation the answer and make the review workflow
    untestable.
    """
    declared = {l["ticket_id"] for l in world["links"]}
    for ticket_id in BOUNDARY:
        assert ticket_id not in declared


def test_the_expected_reports_exist(world) -> None:
    ids = {t["id"] for t in world["tickets"]}
    assert set(ISOLATED) <= ids
    assert set(BOUNDARY) <= ids


def test_hard_negatives_share_a_service_with_the_incident_they_resemble(world) -> None:
    """A hard negative on a different service would be trivially separable.

    Each of these sits on the same service as a live incident, with overlapping
    vocabulary and a genuinely different mechanism.
    """
    by_id = {t["id"]: t for t in world["tickets"]}
    pairings = {
        "TKT-4301": "svc-auth",
        "TKT-4302": "svc-analytics",
        "TKT-4303": "svc-billing",
        "TKT-4304": "svc-api",
        "TKT-4305": "svc-search",
        "TKT-4306": "svc-files",
        "TKT-4307": "svc-notifications",
    }
    for ticket_id, service in pairings.items():
        assert by_id[ticket_id]["service_id"] == service


# --- wave separation --------------------------------------------------------------------


def test_same_service_incidents_have_real_margin(world) -> None:
    """The two analytics incidents must not sit on the 90-minute lifecycle boundary.

    An earlier draft placed them exactly 90 minutes apart, which made authored ground
    truth depend on `<` versus `<=`. The design now requires ≥ 120 minutes.
    """
    by_id = {t["id"]: t for t in world["tickets"]}
    last_1045 = max(
        when(by_id[l["ticket_id"]]["created_at"])
        for l in world["links"]
        if l["incident_id"] == "INC-1045"
    )
    first_1046 = min(
        when(by_id[l["ticket_id"]]["created_at"])
        for l in world["links"]
        if l["incident_id"] == "INC-1046"
    )
    gap = (first_1046 - last_1045).total_seconds() / 60
    assert gap >= 120, f"only {gap:.0f} minutes between the analytics incidents"


def test_wave_b_incidents_genuinely_overlap(world) -> None:
    """Several candidates must be live at once, or a report succeeds by default."""
    by_id = {t["id"]: t for t in world["tickets"]}
    spans = {}
    for incident_id in ("INC-1044", "INC-1045", "INC-1047", "INC-1049", "INC-1048"):
        times = [
            when(by_id[l["ticket_id"]]["created_at"])
            for l in world["links"]
            if l["incident_id"] == incident_id
        ]
        # A candidate keeps accepting for 90 minutes after its last report.
        spans[incident_id] = (min(times), max(times))

    probe = when("2026-08-26T10:15:00Z")
    live = [
        incident_id
        for incident_id, (start, last) in spans.items()
        if start <= probe and (probe - last).total_seconds() / 60 <= 90
    ]
    assert len(live) >= 3, f"only {live} live at 10:15"
