# IncidentIQ — Required Demo Scenarios

These three must keep working. Treat them as regression cases, wired to the real pipeline.

## Scenario A — Correlated major incident

Multiple seemingly separate tickets are correctly grouped into one underlying service
incident. Operational evidence (typically a recent deployment plus service-health
degradation) reveals a plausible root cause. The system recommends remediation and
requests human approval.

Demonstrates: correlation, evidence-backed hypothesis, approval gate.

## Scenario B — Superficially similar tickets, different incidents

Tickets share vocabulary and symptoms but have different causes. The system must **not**
over-cluster them.

Demonstrates: correlation precision — that grouping uses service/entity/temporal signal,
not just text similarity.

## Scenario C — Insufficient evidence

The investigation surfaces multiple plausible explanations with no decisive evidence. The
system **abstains** from recommending a consequential action, states the competing
hypotheses, and names the missing evidence it would need.

Demonstrates: abstention as a designed outcome, and the refusal to guess.

## Rules for all scenarios

- Run through the real pipeline. No scenario-specific branches in production code paths.
- Fixtures are labeled synthetic and visible as such in the UI.
- Each scenario has an eval case, so a regression fails a test rather than surfacing in a
  live demo.
