# IncidentIQ — Evaluation Reference

Evaluation is part of the product. A capability without a metric is not done.

## Metrics

| Capability | Metric |
|---|---|
| Ticket triage | triage accuracy (service / issue type / capability) |
| Priority assignment | priority accuracy |
| Incident correlation | precision |
| Incident correlation | recall |
| Historical retrieval | Recall@K |
| Root-cause hypotheses | Top-K accuracy |
| Recommendation grounding | unsupported recommendation rate |
| Abstention | abstention behavior on insufficient-evidence cases |

## Current baselines

Both rule-driven, no model. See `apps/api/evaluation/`.

**`deterministic-v1`** — triage:

| Suite | Metric | Result |
|---|---|---|
| Authored golden (25 cases, dev set) | service / issue type / priority | 92% / 80% / 88% |
| Polaris (23,994 cases, held out) | priority | 43.1%, against a 58.8% majority-class baseline |

**`deterministic-correlation-v1`** — correlation:

| Suite | Metric | Result |
|---|---|---|
| Authored golden (26 tickets, dev set) | precision / recall / false-merge | 100% / 29% / 0% |
| Polaris outages (held out) | precision / recall / false-merge | 79% / 0.2% / 31% |

Both external numbers are poor, in different ways, and both are the honest state of the
baselines rather than something to close by retuning against the benchmark. Polaris
recall is also structurally limited: its outage events carry 200–500 tickets over 3–4
days, so all-pairs recall punishes a burst detector by construction. Polaris additionally
labels multi-month product *launch* cohorts as events; those are topical, not incidents,
and grouping them would be a false positive.

## Harness expectations

- `EvalCase` / `EvalRun` persist inputs, outputs, metric values, and the model/prompt
  version used, so runs are comparable over time.
- Eval sets are built from the public datasets' ground truth plus a small hand-labeled
  Northstar Cloud set. Polaris ground truth (`event_id`, `event_type`, `topic`, `priority`)
  is label-view only, and the dataset itself is fetched by script rather than committed —
  see [data.md](data.md).
- Runs must be reproducible: fixed seeds, pinned dataset snapshot, recorded configuration.
- Deterministic and retrieval layers get their own tests; do not let LLM variance mask a
  broken similarity function.

## Per-feature evaluation statement

For any AI-related feature, state before calling it complete:

1. **What success means** — in the operator's terms, not the model's.
2. **What dataset / golden set tests it.**
3. **What metric measures it**, and the current number.
4. **What failure case is most concerning** — usually a confident wrong recommendation or a
   missed correlation on a real outage.

## Metrics that matter most

- **Unsupported recommendation rate** is the trust metric. A recommendation citing evidence
  that does not support it is worse than abstaining.
- **Correlation precision** guards against over-clustering (Scenario B).
- **Abstention behavior** guards against confident guessing (Scenario C).

Passing one demo example is not evaluation.
