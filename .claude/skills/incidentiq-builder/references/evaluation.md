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
| Authored golden (33 tickets, dev set) | precision / recall / false-merge | 87.5% / 25.9% / 16.7% |
| Polaris outages (held out) | precision / recall / false-merge | 79% / 0.2% / 31% |

**`semantic-correlation-v1`** — the same correlation plus embedding similarity
(`fastembed:BAAI/bge-small-en-v1.5`, one signal among five). On the authored golden set
it scores **identically** to the deterministic baseline on every metric: it recovers one
true SSO pair the rules missed and loses a different one to the reduced lexical weight.
The guardrails hold — identical text five hours apart is still kept apart.

Two findings worth carrying forward:

- This model rates *same-incident* ticket pairs at 0.65–0.90 cosine and *unrelated* pairs
  at 0.43–0.89. The bands overlap, which is why a calibration floor is needed and why
  paraphrased reports with no shared vocabulary still fall below it.
- Neither version separates two tickets whose text is near-identical but whose **error
  codes differ**: the entity signal rewards shared identifiers and says nothing about
  conflicting ones. That is the clearest next fix, and it is deterministic work.

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
