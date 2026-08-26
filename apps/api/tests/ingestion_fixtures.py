"""Hand-authored source rows mirroring the upstream schemas.

Written by us, small enough to read in one screen, and shaped like the real columns so
the adapters can be tested without downloading either corpus. The values are invented —
these are not copies of upstream records.
"""

ITSM_ROW = {
    "record_id": "INC-TEST-0001",
    "record_type": "incident",
    "status": "closed",
    "ticket": {
        "submitted_at": "2025-11-18T08:00:00Z",
        "submitted_title": "VPN client disconnects every few minutes",
        "submitted_description": "The VPN drops roughly every five minutes on the "
        "office network and reconnects on its own.",
        "priority": "high",
        "sla_plan": "gold",
        "environment": {
            "os": "macOS 15",
            "platform": "laptop",
            "region": "emea",
            "user_group": "field-sales",
        },
        "applications": ["VPN Client", "Network Access Control"],
    },
    "correspondence": [
        {
            "turn_id": 1,
            "role": "agent",
            "event_type": "diagnostic_question",
            "message": "Does the drop happen on other networks?",
            "timestamp": "2025-11-18T08:12:00Z",
        },
        {
            "turn_id": 2,
            "role": "user",
            "event_type": "user_reply",
            "message": "It is fine at home, only the office network drops.",
            "timestamp": "2025-11-18T08:30:00Z",
        },
    ],
    "diagnostics": {
        "coverage": "standard",
        "summary": "Session logs show renegotiation failures against one gateway.",
        "observed_errors": ["IKE_SA rekey timeout", "tunnel teardown code 21"],
        "steps": [{"step_id": "S1", "action": "collected client logs"}],
    },
    "root_cause": "One gateway in the pool had a stale rekey timer, dropping sessions "
    "at every renegotiation.",
    "resolution": {
        "steps": [
            "Drained the affected gateway from the pool.",
            "Restored the rekey timer to the standard value and returned it to service.",
        ]
    },
}

POLARIS_ROW = {
    "ticket_id": "TCK-TEST-01",
    "created_at": "2024-03-04T11:22:33",
    "channel": "email",
    "plan": "growth",
    "user_role": "analyst",
    "reported_category": "billing",
    "subject": "Dashboard will not load",
    "body": "The revenue dashboard has been spinning for ten minutes.",
    # Ground truth below this line.
    "topic": "dashboards",
    "type": "bug",
    "priority": "high",
    "routing": "tier2_support",
    "sentiment": "frustrated",
    "event_id": "EVT-TEST-SEV1",
    "event_type": "outage",
}

POLARIS_LABEL_VALUES = (
    "dashboards",
    "bug",
    "tier2_support",
    "frustrated",
    "EVT-TEST-SEV1",
    "outage",
)


def polaris_row(ticket_id: str, **overrides: object) -> dict:
    return {**POLARIS_ROW, "ticket_id": ticket_id, **overrides}
