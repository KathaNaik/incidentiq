# Northstar Cloud — synthetic development fixtures

**Northstar Cloud is a fictional company. Every record here is fabricated.** No real
customer, user, incident, or ticket is represented, and none of these records is derived
from any external dataset.

These fixtures were authored specifically for IncidentIQ. They are not copies,
paraphrases, translations, or adaptations of the Polaris (CC BY-SA 4.0) or MIT
synthetic-ticket datasets — neither dataset has been ingested into this project yet. See
[../../../docs/DATA_SOURCES.md](../../../docs/DATA_SOURCES.md).

## Files

Each file is an envelope: `{"dataset": ..., "synthetic": true, "records": [...]}`. The
loader rejects any file whose `synthetic` flag is not true, so an unlabelled dataset
cannot quietly become what the UI shows.

| File | Records |
|---|---|
| `services.json` | 3 services |
| `tickets.json` | 11 tickets |
| `incidents.json` | 2 incidents |
| `incident_tickets.json` | 8 incident↔ticket links |

## What the data is shaped to exercise

- **INC-1042** — five tickets, arriving within 40 minutes, all describing sign-in failure
  in different words. The cluster a correlator should find.
- **INC-1043** — three tickets spanning two services, where a connector backlog surfaces
  to users as stale dashboards.
- **Standalone tickets** — TKT-4108 (export truncation) and TKT-4109 (slow reset email)
  share vocabulary with the two incidents but have unrelated causes; grouping them in
  would be an over-clustering error.
- **TKT-4114** — no service, no priority, thin detail. An untriaged ticket, and the kind
  of case where a system should say it does not know rather than guess.

**Incident↔ticket links here are declared by hand.** Nothing infers them. When correlation
is implemented, these become the labels it is measured against — not an input to it.

## Editing

The loader validates referential integrity on load: unknown service or ticket ids,
duplicate ids, and a ticket linked to two incidents all raise `FixtureError` at startup.
Timestamps must carry a timezone offset.
