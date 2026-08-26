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
