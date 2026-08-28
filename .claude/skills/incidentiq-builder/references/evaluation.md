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
| Polaris outages (held out) | precision / recall / false-merge | 79.0% / 0.2% / 31.1% |

**`semantic-correlation-v1`** — the same correlation plus embedding similarity
(`fastembed:BAAI/bge-small-en-v1.5`, one signal among five). On the authored golden set
it scores **identically** to the deterministic baseline on every metric: it recovers one
true SSO pair the rules missed and loses a different one to the reduced lexical weight.
The guardrails hold — identical text five hours apart is still kept apart.

On the held-out Polaris outages it does slightly better and slightly worse at once:
precision 79.7% (from 79.0%) and 1,393 true pairs found instead of 1,187 — about 17%
more recall — while the false-merge rate rises from 31.1% to 32.1%. Event recovery stays
at zero for both.

Two findings worth carrying forward:

- This model rates *same-incident* ticket pairs at 0.65–0.90 cosine and *unrelated* pairs
  at 0.43–0.89. The bands overlap, which is why a calibration floor is needed and why
  paraphrased reports with no shared vocabulary still fall below it.
- Neither version separates two tickets whose text is near-identical but whose **error
  codes differ**: the entity signal rewards shared identifiers and says nothing about
  conflicting ones. That is the clearest next fix, and it is deterministic work.

**`historical-retrieval-v1`** — precedent retrieval over 751 records (6 authored
Northstar + 745 external):

| Suite | Metric | Result |
|---|---|---|
| External corpus, leave-one-out | Recall@1 / @3 / @5 | 99.9% / 100% / 100% (random baseline 7.1% / 19.8% / 30.7%) |
| Authored Northstar scenarios | correct precedent at rank 1 | 5 of 5, plus a deliberately vague query correctly marked as having no strong match |

**Read that first row with the caveat.** The external corpus is 14 tight clusters of
near-paraphrases — intra-family cosine median 0.89 against 0.63 between families — so
"find another record from the same family" is closer to duplicate detection than to
finding precedent across genuinely different incidents. It confirms the pipeline works;
it does not establish the capability. Reranking on service and error identifiers changed
these numbers not at all, and a title-only query slice still scored 99.1% Recall@1.

**`investigation-v1`** — the AI investigator, over typed evidence:

| Suite | Metric | Result |
|---|---|---|
| Retrieval-only baseline (16 authored cases) | leading hypothesis / abstention | 83.3% (5/6 answerable) / 37.5% |
| `gpt-5.6-terra` (2026-08-27, one held-out run) | leading hypothesis / abstention | **100% (6/6) / 75%** |

Full investigator run: structured-output validity 100%, top-3 accuracy 100%,
unsupported citation rate 0%, unsupported remediation rate 0%, required-evidence
coverage 100% (6/6). Median latency 10.7 s over 16 calls; 35,449 input and 12,445
output tokens.

**The abstain flag is not stable across runs.** A verification pass minutes after the
recorded run returned the opposite decision on two cases (IV01, IV16), with correct
hypotheses either way. The 75% figure is therefore one sample of a non-deterministic
behaviour, not a fixed property, and repeating the run until it improved would have been
tuning against the held-out set.

The investigator recommended **no remediation on any case**, including the four where a
rollback was supportable. That keeps the unsupported-remediation rate at zero for a
reason that is not entirely a virtue, and the harness does not currently measure *missed*
remediation.

The baseline is the number to beat and it says something specific: nearest-neighbour
retrieval names a plausible cause reasonably often, and is wrong about *when not to
answer* almost two thirds of the time, because it never abstains. Abstention is the gap.

Investigation metrics are graded programmatically — evidence ids cited, abstention
correctness, unsupported citation rate, unsupported remediation rate, required-evidence
coverage, structured-output validity. Only "named the right cause" uses a proxy (accepted
cause terms in the leading hypothesis); no LLM judge is used, and one should not be added
until the deterministic signals stop discriminating.

**Known limitation carried forward from M5/M6, not fixed here:** both correlation
versions may false-merge near-identical tickets whose strong error identifiers *differ*,
because entity scoring rewards matches and does not penalize conflicts. The evaluated
baselines were deliberately left unchanged.

Both external correlation numbers are poor, in different ways, and both are the honest state of the
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
