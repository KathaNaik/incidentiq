# IncidentIQ — Architecture Reference

## Stack

- **Frontend:** Next.js, TypeScript, Tailwind
- **Backend:** Python, FastAPI
- **Storage:** PostgreSQL; pgvector once vector retrieval is actually introduced

Do not add infrastructure (queues, caches, orchestrators, extra services) unless a specific
MVP capability requires it and the Tenex demo is better for it.

## Domain concepts

These are the *likely* concepts, not a schema to build up front:

`Ticket`, `Incident`, `IncidentTicket`, `Service`, `Deployment`, `ServiceHealth`,
`HistoricalIncident`, `Runbook`, `Investigation`, `Evidence`, `Recommendation`, `Action`,
`AuditEvent`, `EvalCase`, `EvalRun`.

**Introduce each one only when the feature being built actually requires it.** A table or
class that exists because it appeared on this list is premature abstraction.

## Layer split (apply per feature)

### Deterministic
Timestamps, counts, state transitions, SLA calculations, approval thresholds, audit
logging, authorization, database lookups, action execution. This is the backbone — it must
be correct without any model in the loop.

### Statistical / retrieval
Embeddings, similarity scoring, clustering, retrieval ranking. Tunable, measurable, and
testable with fixed inputs. Correlation blending lives here, not in a prompt.

### LLM reasoning
Unstructured ticket interpretation, evidence synthesis, root-cause hypothesis generation,
explaining tradeoffs, recommending next investigations. Everything the LLM returns should
be a validated structured schema with an explicit abstain path.

## Investigation tools

Investigation tools are typed functions over the database and fixtures, not free-form
model access:

| Tool | Returns |
|---|---|
| `search_related_tickets` | tickets similar in service/entity/time window |
| `search_past_incidents` | historically resolved incidents with cause + resolution |
| `get_recent_deployments` | deployments touching a service inside a time window |
| `get_service_health` | health/error-rate signals for a service over time |
| `search_runbooks` | runbook passages matching a symptom or service |
| `get_error_summary` | aggregated error signatures and counts |

Each tool: typed input, typed output, deterministic given the same data, independently
testable, and cheap to log. Tool call traces are evidence — persist them.

## Evidence and abstention

- Every `Recommendation` links to the `Evidence` records that support it.
- An unsupported claim in a recommendation is a bug, not a style issue.
- The investigator must be able to return "insufficient evidence" plus the missing evidence
  it would need. Abstention is a first-class outcome, not a failure path.

## Approval boundary

For any consequential action:

- typed inputs
- explicit state machine (e.g. proposed → pending_approval → approved/rejected → executed/failed)
- an authorization check at the boundary, not sprinkled through callers
- an `AuditEvent` for every transition, including who and when
- idempotency where re-execution is possible

Simulated execution is acceptable in the prototype and **must be labeled as simulated in
both the API response and the UI**. Never present a simulated action as a real integration.
