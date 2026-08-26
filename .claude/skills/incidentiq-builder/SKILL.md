---
name: incidentiq-builder
description: Operating procedure for building IncidentIQ, an AI-assisted incident investigation system for technical operations teams (Tenex Build First challenge). Use for any IncidentIQ implementation, design, data, evaluation, demo, or commit work — ticket intake, incident correlation, investigation tools, human-approved remediation, and the evaluation harness.
---

# IncidentIQ Builder

Guides implementation of **IncidentIQ**: an AI-assisted incident investigation system for
technical operations / incident-response teams.

**Core transformation:**

```
fragmented technical support tickets + operational context
  → correlated incident
  → evidence-backed root-cause hypothesis
  → recommended remediation
  → human approval
```

**IncidentIQ is NOT** a generic chatbot, a ticket-response assistant, a fully autonomous
agent, or a multi-agent demo for its own sake. If a proposed change pushes it toward any of
those, say so and propose the alternative.

## Product principles (enforce on every request)

1. Build for the technical operations / incident-response user.
2. Optimize for measurable workflow transformation, not AI novelty.
3. Deterministic backbone, selective AI reasoning.
4. Never use an LLM where straightforward deterministic logic is more reliable.
5. Consequential remediation actions require human approval.
6. Every AI-generated recommendation must be grounded in explicit evidence.
7. The system must be able to **abstain** when evidence is insufficient.
8. Structured schemas for AI outputs wherever practical.
9. Every major AI capability must be evaluatable.
10. A narrow, polished workflow beats feature breadth.
11. Synthetic, public, or legally permissible data only, used within its license terms.
12. No integrations or infrastructure that do not improve the Tenex demo.
13. Avoid overengineering.
14. Production-grade engineering standards even when actions are simulated.
15. Clear incremental Git history. No giant bundled commits.

## MVP scope

Five capabilities. Anything outside them needs an explicit justification.

1. **Ticket intake** — unstructured ticket → affected service, issue type, priority,
   symptoms, entities, affected capability. Deterministic extraction first; LLM structured
   extraction only for what deterministic logic cannot reach.
2. **Incident correlation** — group tickets representing one underlying incident using
   semantic similarity + temporal proximity + shared services/entities + issue
   classification. **Never** implement this as "ask an LLM if these two tickets are related."
3. **Incident investigation** — typed tools: `search_related_tickets`,
   `search_past_incidents`, `get_recent_deployments`, `get_service_health`,
   `search_runbooks`, `get_error_summary`. The model synthesizes evidence into hypotheses,
   confidence, supporting evidence, missing evidence, recommended next action.
4. **Human-approved remediation** — consequential actions pass an explicit approval
   workflow. Simulated execution is fine; typed inputs, state transitions, an authorization
   boundary, audit events, and idempotency where relevant are not optional.
5. **Evaluation** — part of the product, not an afterthought. See
   [references/evaluation.md](references/evaluation.md).

## Architecture rule

Before implementing any feature, split its behavior into three layers and state the split:

| Layer | Belongs here |
|---|---|
| **Deterministic** | timestamps, counts, state transitions, SLA math, approval thresholds, audit logging, authorization, DB lookups, action execution |
| **Statistical / retrieval** | embeddings, similarity, clustering, retrieval ranking |
| **LLM reasoning** | unstructured ticket interpretation, evidence synthesis, root-cause hypotheses, explaining tradeoffs, recommending next investigations |

**If an LLM is proposed for something deterministic software does reliably, stop and
reconsider.** Say why out loud before proceeding.

Stack and domain concepts: [references/architecture.md](references/architecture.md).

## Workflow when this skill is invoked

Run these steps for every implementation request. Keep the written output terse — a few
lines per step, not an essay.

**1 — Understand.** Read the relevant existing code before changing anything. Identify the
user-visible goal, current implementation, relevant domain models, affected
frontend/backend boundaries, existing tests, existing conventions. Do not assume
architecture from the prompt; the repository may have evolved past it.

**2 — Scope.** State the smallest coherent change achieving the requested outcome, and
explicitly name what you are deliberately *not* implementing. No opportunistic refactors.

**3 — Design.** Briefly determine: deterministic components, retrieval/statistical
components, LLM components, data contracts, failure states, observability needs,
evaluation method. For consequential actions, name the approval boundary.

**4 — Implement.** The smallest production-quality vertical slice.
*Prefer:* typed interfaces, clear module boundaries, structured AI outputs, explicit
errors, testable functions, deterministic fallbacks.
*Avoid:* hidden prompt magic, god classes, unnecessary agents, premature abstractions,
mocked behavior presented as real integration, hard-coded demo outputs disguised as model
reasoning.

**5 — Test.** Run the relevant unit tests, integration tests, type checks, linting, and
eval cases. Add tests for meaningful failure modes, not only happy paths.

**6 — Evaluate.** For any AI-related feature state: what success means, what
dataset/golden set tests it, what metric measures it, what failure case is most concerning.
An AI feature is not complete because one demo example works.

**7 — Review.** Inspect the diff and check:
- Does this improve the target user's workflow?
- Is AI used only where justified?
- Is evidence traceable?
- Can the model abstain?
- Are consequential actions gated?
- Is demo-only behavior clearly labeled?
- Is external data used within its license — no committed Polaris data, attribution current?
- Is the feature evaluatable?
- Did unnecessary scope creep in?
- Could every tradeoff be explained to a Tenex engineer?

Fix obvious issues before reporting completion.

**8 — Report.** Concise summary: (1) what changed, (2) important architecture decisions,
(3) tests/evals run, (4) known limitations, (5) the logical next step. No marketing
language.

## Data

Two license-reviewed public datasets plus a small controlled fixture set for the demo org
**Northstar Cloud**. Ground-truth fields (e.g. event IDs) used as evaluation labels must
never leak into model or runtime features.

Licensing decision — already made, follow it:

- `ameau01/synthetic-it-support-tickets` (**MIT**) — approved for use in the application;
  preserve attribution and the license notice.
- `VladislavMarinovich/polaris-support-tickets-v2` (**CC BY-SA 4.0**) — approved as an
  *external evaluation dataset only*. Never commit the raw or processed data; ship a
  reproducible download script and gitignore `data/raw/` and `data/processed/`. Never
  present it as our own synthetic data. **Flag before distributing any adapted copy** —
  ShareAlike obligations would apply.
- Northstar Cloud demo fixtures must be **original work we generate** and labeled synthetic.
  Renaming or lightly editing Polaris records into Northstar Cloud data is not acceptable.
- Sources, licenses, attribution, and constraints are recorded in
  [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md); keep it current when data handling changes.

Details, dataset roles, repo layout, and leakage rules:
[references/data.md](references/data.md).

## Demo scenarios

Three scenarios must keep working: a correlated major incident, superficially similar
tickets that are *not* one incident, and an insufficient-evidence case that abstains.
See [references/demo-scenarios.md](references/demo-scenarios.md).

## Git behavior

Do **not** commit automatically. Only commit when explicitly asked.

When asked to commit: inspect the diff first, confirm the change is coherent, avoid mixing
unrelated changes, and suggest a concise descriptive message.

The history should naturally read like: initialize application architecture → add incident
data models → add synthetic dataset ingestion → implement ticket triage → implement
incident correlation → add historical incident retrieval → build investigation tools → add
evidence-backed recommendations → add approval and audit workflow → build evaluation
harness → build operations dashboard → polish controlled demo scenarios.
Do not artificially manufacture commit history.

## Tenex filter

When multiple approaches are technically valid, choose the one that better demonstrates:
end-user workflow understanding, production-grade engineering judgment, measurable business
impact, appropriate AI usage, reliability and evaluation, and pragmatic scope control.

This is a functional prototype demonstrating transformation potential — not a production
SaaS company.
