# IncidentIQ

AI-assisted incident investigation for technical operations teams.

IncidentIQ turns fragmented technical support tickets plus operational context into a
correlated incident, an evidence-backed root-cause hypothesis, and a recommended
remediation that a human approves before anything runs.

**Status:** the full workflow runs end to end. Tickets correlate into candidate incidents,
a language model investigates one against typed evidence it must cite by id, deterministic
action-specific policy decides whether its recommendation may be approved, and a human
approves before a simulated execution. Every stage has a measured baseline and an
evaluation artifact; the deterministic stages use no model at all. Execution is simulated
throughout — no infrastructure is contacted.

## Repository layout

```
apps/
  api/       FastAPI backend (Python, uv)
    ingestion/  offline adapters for the external datasets
    scripts/    download and preprocess commands
  web/       Next.js frontend (TypeScript, Tailwind, npm)
data/
  demo/      Northstar Cloud fixtures — synthetic, authored for this project
  raw/       downloaded datasets — gitignored
  processed/ normalized datasets — gitignored
docs/        DATA_SOURCES.md: dataset licenses and attribution
```

## Prerequisites

- Node.js 20.9+ (developed on 23.11) and npm
- [uv](https://docs.astral.sh/uv/) — manages the Python toolchain and virtualenv
- Python 3.13 (uv installs it if missing)
- Docker, for PostgreSQL with the pgvector extension

## Start the database

Investigation runs, actions, approvals, executions, audit events and the historical
corpus all live in PostgreSQL. Only the database is containerised — the API and web app
run on the host.

```bash
docker compose up -d                       # PostgreSQL 17 + pgvector on port 5434
cd apps/api
cp .env.example .env                       # DATABASE_URL, and OPENAI_API_KEY if you have one
uv sync
uv run alembic upgrade head                # empty database -> current schema, extension included
uv run --group semantic python scripts/import_historical.py
uv run python scripts/seed_tickets.py            # authored Northstar tickets
```

`seed_tickets.py` is idempotent and **distinct from `POST /demo/reset`**: seeding loads
operational input, reset clears workflow state. Running one does not undo the other.

Port 5434 rather than 5432 because a developer machine usually already has PostgreSQL
somewhere, and a port collision is a confusing first-run failure.

The import is safe to re-run: records are keyed by stable corpus id and embeddings are
reused from the on-disk cache, so a second run takes well under a second.

Schema changes go through Alembic. `create_all()` is deliberately not the strategy — an
empty database plus migrations is the only supported path to a working schema, and a test
verifies it.

## Run the backend

```bash
cd apps/api
uv sync
uv run uvicorn app.main:app --reload --port 8001
```

The API serves on <http://localhost:8001>; `/health` returns
`{"status": "ok", "service": "incidentiq-api"}` and `/docs` has the OpenAPI UI.

Read-only endpoints:

| Endpoint | Returns |
|---|---|
| `GET /health` | liveness |
| `GET /dataset` | which dataset is being served, and that it is synthetic |
| `GET /services` | services, ordered by name |
| `GET /tickets` | tickets, newest first |
| `GET /tickets/{id}` | one ticket plus the incident it belongs to (404 if unknown) |
| `GET /incidents` | incidents, most recently detected first, with ticket counts |
| `GET /incidents/{id}` | one incident with its linked tickets (404 if unknown) |
| `POST /triage` | deterministic triage of supplied ticket text |
| `GET /tickets/{id}/triage` | deterministic triage of a stored ticket (404 if unknown) |
| `POST /correlation/analyze` | candidate incidents from supplied tickets |
| `GET /correlation/candidates` | candidate incidents across the stored ticket set |
| `GET /evals/triage` | the committed triage evaluation artifact |
| `GET /evals/correlation` | the committed correlation evaluation artifact |
| `GET /evals/correlation/comparison` | deterministic versus semantic, with per-slice examples |
| `POST /retrieval/historical-incidents` | past incidents resembling a described situation |
| `GET /correlation/candidates/{id}/similar` | precedent for one candidate incident |
| `GET /evals/retrieval` | the committed historical-retrieval evaluation |
| `POST /incidents/{id}/investigations` | run an investigation — the **only** endpoint that calls a model |
| `GET /incidents/{id}/investigations` | run history, newest first |
| `GET /incidents/{id}/investigations/latest` | the stored investigation, or 204 if none |
| `GET /investigations/{id}` | one exact run, with the evidence snapshot it saw |
| `GET /investigations/{id}/timeline` | chronology recomputed from that run's own snapshot |
| `GET /evals/investigation` | investigation metrics (`?version=v1`, `v2` or `baseline`) |
| `POST /incidents/{id}/actions` | propose an action from a remediation recommendation |
| `GET /incidents/{id}/actions` | actions proposed for an incident |
| `POST /actions/{id}/approve` | explicit human approval |
| `POST /actions/{id}/reject` | explicit human rejection |
| `POST /actions/{id}/execute` | run the simulated action (idempotent) |
| `GET /actions/{id}/audit` | the action's audit trail |
| `GET /evals/policy` | action-policy suite results |
| `GET /evals/policy/replay` | policy-v1 versus policy-v2 on identical recorded recommendations |
| `GET /actions` | every action this process has seen (dashboard counts) |
| `POST /tickets` | submit a report — validate, persist, triage, correlate. No model call. |
| `GET /intake/tickets` | runtime tickets with triage and correlation state |
| `GET /intake/tickets/{id}` | one runtime ticket |
| `GET /intake/candidates` | persisted candidate incidents and their membership |
| `GET /correlation-reviews` | the review queue (`?pending_only=false` for decided ones too) |
| `GET /correlation-reviews/{id}` | one review with the snapshot it was raised against |
| `POST /correlation-reviews/{id}/confirm` | operator: same incident — attaches the ticket |
| `POST /correlation-reviews/{id}/reject` | operator: different incident — records the label |
| `POST /demo/reset` | clears workflow state (development only) |
| `POST /demo/policy-probe` | what policy *would* decide about an action nobody recommended (development only) |

Both correlation endpoints take `?mode=deterministic` (the default) or `?mode=semantic`,
and `/evals/correlation` takes `?version=`. The version is stamped on every response.

Tickets, services and incidents come from the fixture directory in
`data/demo/northstar_cloud`, loaded and validated at startup — they are authored demo
input, versioned with the code rather than stored in the database.

Everything the product is *stateful* about lives in PostgreSQL and survives a restart:
investigation runs with their evidence snapshots, actions, approvals, execution results,
audit events, and the historical corpus with its vectors. Evaluation artifacts stay on
disk: a benchmark result is a record of a measurement that already happened, and putting
it somewhere mutable would invite it to change.

`POST /demo/reset` clears workflow state so the walkthrough can be run twice. Both demo
endpoints refuse to run when `INCIDENTIQ_ENVIRONMENT=production`.

Port 8001 rather than the usual 8000, which is often already taken by another local
service. If 8001 is busy too, pass a different `--port` and point the frontend at it via
`NEXT_PUBLIC_API_BASE_URL`.

## Run the frontend

```bash
cd apps/web
npm install
cp .env.example .env.local   # only needed if the API is not on http://localhost:8001
npm run dev
```

The app serves on <http://localhost:3000>. The Dashboard calls the backend's `/health`
from the browser and reports whether the API is reachable — with the backend stopped it
shows an explicit "API unreachable" state rather than pretending.

| Page | What it is for |
|---|---|
| `/` | operations dashboard — counts, incident queue, what is waiting on a person |
| `/incidents` | detected incidents, and one incident end to end |
| `/tickets` | the runtime ticket queue, with triage and correlation state |
| `/reviews` | [correlation review](#operator-correlation-review) — the groupings automation declined to decide |
| `/evals` | measured results, in the order the system was built |

## Checks

```bash
cd apps/api && uv run pytest              # backend tests (needs PostgreSQL for the `pg` suite)
cd apps/api && uv run pytest -m "not pg"  # fast suite only — no database required
cd apps/web && npm run typecheck  # tsc --noEmit
cd apps/web && npm run lint       # eslint
cd apps/web && npm run build      # production build
```

## Configuration

| Variable | Where | Default | Purpose |
|---|---|---|---|
| `INCIDENTIQ_SERVICE_NAME` | api | `incidentiq-api` | Service identity in `/health` |
| `INCIDENTIQ_ENVIRONMENT` | api | `local` | `local` / `test` / `production` |
| `INCIDENTIQ_CORS_ALLOW_ORIGINS` | api | `["http://localhost:3000"]` | Browser origins allowed to call the API (JSON list) |
| `INCIDENTIQ_FIXTURES_DIR` | api | `data/demo/northstar_cloud` | Fixture dataset the API serves |
| `INCIDENTIQ_EMBEDDINGS_CACHE_DIR` | api | `data/processed/embeddings` | Where ticket vectors are cached |
| `NEXT_PUBLIC_API_BASE_URL` | web | `http://localhost:8001` | Backend base URL used by the browser |
| `OPENAI_API_KEY` | api | _(unset)_ | Credentials for investigation. Nothing else needs it. |
| `INCIDENTIQ_INVESTIGATION_MODEL` | api | `gpt-5.6-terra` | Model used for investigation |

CORS is open to the local Next.js dev server only. Any deployed environment must set
`INCIDENTIQ_CORS_ALLOW_ORIGINS` explicitly.

## External datasets

Two public datasets are downloaded and normalized offline for later retrieval and
evaluation work. They are not served by the API and not committed:

```bash
cd apps/api
uv run python scripts/download_itsm.py && uv run python scripts/preprocess_itsm.py
uv run python scripts/download_polaris.py && uv run python scripts/preprocess_polaris.py
```

Polaris ground truth is written to a separate `labels.jsonl`, structurally isolated from
the features. Details in [data/README.md](data/README.md).

## Baselines and evaluation

Two deterministic baselines, both rule-driven with no model or embeddings anywhere:

- **`deterministic-v1`** — triage. Service, issue type and priority from ticket text.
  Rules in [app/triage/rules.py](apps/api/app/triage/rules.py).
- **`deterministic-correlation-v1`** — correlation. Groups tickets into *candidate*
  incidents using time decay, service and issue agreement, IDF-weighted word overlap and
  shared identifiers. Weights and thresholds in
  [app/correlation/rules.py](apps/api/app/correlation/rules.py).
- **`deterministic-correlation-v2`** — the live default. Identical scoring to v1 — same
  weights, same thresholds, same time decay — with one changed semantic: how a recomputed
  cluster is reconciled onto a durable candidate. See
  [safe reconciliation](#safe-reconciliation-deterministic-correlation-v2) below. v1 stays
  selectable and reproduces its own defect on demand.
- **`semantic-correlation-v1`** — the same correlation with one extra signal: cosine
  similarity between ticket embeddings. Same candidate generation, same guardrails, so
  the two are directly comparable. Opt-in everywhere; deterministic stays the default.
- **`historical-retrieval-v1`** — given a current incident, finds resolved incidents that
  looked like it, and shows what those turned out to be. Retrieval matches *symptoms
  only*; a historical cause and fix are displayed after a match, never used to make one.
- **`investigation-v2`** — the default investigator, and the only place a language model
  runs. `investigation-v1` is preserved, selectable by name, and frozen; see the
  experiment below.
- **`investigation-v1`** — the original investigator, kept for reproducibility. It receives a fixed set
  of typed evidence, returns ranked hypotheses citing that evidence *by id*, and its
  output is validated against the registry before anyone sees it. It recommends
  remediation; it never executes anything.

Correlation is incremental: tickets are processed in arrival order and compared only
against still-active candidates, so the evaluation measures what a running system could
actually have known. Candidates are proposals — nothing creates an `Incident`.

```bash
cd apps/api
uv run python scripts/evaluate_triage.py --suite golden          # authored dev set, committed
uv run python scripts/evaluate_correlation.py --suite golden     # authored dev set, committed
uv run python scripts/evaluate_triage.py --suite polaris         # external benchmark, local only
uv run python scripts/evaluate_correlation.py --suite polaris    # external benchmark, local only

# Semantic correlation, and the baseline-versus-semantic comparison:
uv sync --group semantic
uv run --group semantic python scripts/evaluate_correlation.py --suite golden --mode both
uv run --group semantic python scripts/evaluate_retrieval.py
uv run --group semantic python scripts/evaluate_investigation.py --baseline   # no key needed
uv run --group semantic python scripts/evaluate_investigation.py --model      # needs OPENAI_API_KEY

# Investigator v2, and the development set used to build it without touching the held-out cases:
uv run --group semantic python scripts/evaluate_investigation.py --model --prompt investigation-v2
uv run --group semantic python scripts/evaluate_investigation.py --model --prompt investigation-v2 --dev
```

Historical retrieval needs the ITSM corpus (`scripts/download_itsm.py` and
`preprocess_itsm.py`); without it the index still builds from the authored Northstar
records alone.

### Ticket intake

**"Real intake" here means a typed runtime API and a form.** There is no ServiceNow,
Slack, or email integration, and nothing in this milestone implies one — IncidentIQ does
not talk to any third-party ticketing system.

```
POST /tickets   →  validate  →  persist  →  deterministic triage
                →  replay the active window through correlation
                →  attach / create a candidate / stay uncorrelated
```

**No model is called.** Intake is arithmetic and rule matching, which keeps it fast, free
of token cost, and predictable enough to evaluate. Investigation stays an explicit
operator decision.

**Idempotency** is keyed on `external_id` and backed by a unique constraint. An identical
resubmission returns the original outcome with 200 and correlates nothing twice; the same
id with different content is a 409, because two reports cannot share one identity and
overwriting the first would discard something somebody filed.

**Two timestamps.** `created_at` is when the reporter observed the problem and is what
correlation and the M14 chronology use; `received_at` is when we were told. A report filed
late describes an old event, and arrival time is never allowed to redefine incident onset.

**Correlation is not reimplemented.** Intake replays the tickets in the active window
through the same `correlate()` the batch baseline uses — same signals, same thresholds,
same complete-linkage and cohesion guardrails. A second scoring implementation would drift
from the one M5 and M6 measured, and the evaluated number would stop describing the
running system. "Incremental" here means feeding it a window rather than all history; the
engine already processes chronologically and only offers a ticket to candidates that are
still open.

**Live mode is deterministic**, chosen on measurement rather than preference: on the
authored online set it scores 8/8 against semantic's 7/8, runs in about 6 ms against
635 ms, and needs no embedding call — so no embedding failure mode exists at intake.
Semantic remains available for batch comparison. Reconciliation runs
`deterministic-correlation-v2`; the scoring is v1's, unchanged.

### Safe reconciliation (`deterministic-correlation-v2`)

`correlate()` is stateless — every intake re-derives clusters from the window and knows
nothing about what is already persisted. Intake then has to decide which durable candidate
a fresh cluster *is*, and it answers that by membership overlap. That much is right: a
candidate an operator is already looking at should keep its identity as it grows.

Under v1 the same overlap silently answered a second question — *whether the arriving
ticket belongs there at all*. It does not follow, and operator review is what made the gap
visible. Measured on the M19 acceptance run:

```
durable candidate  = {A, B, C}    C attached by an operator through review
recomputed cluster = {C, D}       legitimate on its own terms, 0.6369
```

The cluster overlapped the candidate at C, so every member of it was assigned to the
candidate. D joined A and B having scored **0.4054** and **0.4577** against them — the
members it was actually joining — against a 0.60 threshold. A performance complaint became
part of a sign-in incident, and no operator was asked.

Nothing about the operator's decision was wrong and nothing about the cluster was wrong.
Identity reconciliation was being allowed to imply membership.

**v2 changes exactly one thing.** An arriving ticket may join an existing durable candidate
only if it clears the engine's own attachment rule against that candidate's
*automatically established* members. Identity reconciliation by overlap is unchanged. No
weight, threshold or time-decay parameter differs between v1 and v2.

Operator-confirmed members are deliberately excluded from that comparison, and the
distinction is worth being exact about, because it is not "human decisions are
second-class data":

- A confirmed ticket stays a **full member** of the incident — evidence, timeline,
  candidate metadata, investigations. Nothing is removed.
- What it does not do is **vouch for a stranger**. The operator answered one question about
  one ticket; that answer is not evidence about a future ticket, in either direction.

Measurement forced that design. Requiring complete linkage against the *full* durable
membership closes the false merge but breaks the honest case — a genuine later report
scored 0.5366 against the widened membership and would have been refused, purely because
the confirmed paraphrase is worded unlike everything else. Judged against the automatic
core, both come out right:

| arriving ticket | vs automatic core `{A, B}` | outcome |
|---|---|---|
| unrelated performance complaint | min **0.4054** | refused, sent to review |
| genuine later sign-in report | min **0.6256** | attached |

So a confirmation neither smuggles a stranger in nor freezes the incident. Membership
provenance comes from `correlation_reviews`, so this needed no schema change.

**Why the evals did not catch it.** The authored online set runs `correlate()` directly
over a seed plus an arriving ticket — no database, no durable candidate, no reconciliation.
It measures the engine, and the defect was in the seam between the engine and persistence.
v1 and v2 score identically there by construction, which is a statement about the set's
coverage rather than evidence that v2 is safe; the PostgreSQL intake and reconciliation
suites are what actually cover it.

**Known consequence.** A refused ticket stays standalone in the window, where the stateless
engine can still cluster it with a confirmed paraphrase. A later genuine report can then
land within `CANDIDATE_MARGIN` of two groupings and be called *ambiguous* instead of
attaching. That is the existing ambiguity guard declining to invent certainty — the ticket
goes to an operator rather than into the wrong incident — but it is a weaker outcome than
attaching, and it is reproduced in
[test_reconciliation_v2.py](apps/api/tests/test_reconciliation_v2.py).

v1 remains selectable (`correlation_reconciliation=v1`) and its test reproduces the false
merge, so the fix stays demonstrable rather than merely asserted.

**A candidate appears on the second compatible report, not the first.** One report is a
singleton, which is a valid operational state shown as "uncorrelated" rather than hidden.
The window a candidate stays open for is the correlation baseline's own
`CANDIDATE_IDLE_MINUTES` (90), reused rather than redefined — a second number here would
give live intake different semantics from the thing that was measured.

**Candidate metadata is derived from members, never incremented**, so a count and its
membership cannot drift apart. Titles are deterministic (`Auth integration incident`); no
model names an incident.

**The correlation decision is recorded at intake** — version, score, confidence, signals,
reason — so "why was this grouped last Tuesday?" survives a later change to thresholds.

Measured intake cost: **30.8 ms end to end** (p50 31.8, p95 42.1), of which triage is
0.22 ms and correlation 5.9 ms over the replay window. The rest is HTTP and two database
transactions.

### Operator correlation review

Correlation has a middle. Near-duplicates attach on their own, clear conflicts are refused
on their own, and neither needs a person. What is left is the slice where a plausible
candidate exists and the deterministic pass declined to commit — reports that are probably
the same incident said in different words, which is exactly the case
[M16, M17 and M18 each failed to recover automatically](#embeddings).

**Review at `/reviews`.** Each item asks one question against one candidate, and the two
answers are *Same incident* and *Different incident*. Not approve and deny: nothing is
being authorised here, a question about the world is being answered, and a button labelled
"Approve" would produce labels whose meaning depended on what the operator thought they
were approving.

A ticket waiting on review shows as **Needs review** in the ticket queue and on the ticket
itself, and the dashboard carries the pending count beside the other things waiting on a
person.

**What a decision is recorded against.** Candidate membership moves. A label saying only
"these two belong together" would, a week later, describe a grouping nobody actually
judged. So each review stores an immutable snapshot — the arriving report, the candidate
and its members, the deterministic signals, and the `pairwise-features-v1` values computed
at the time — and a fingerprint over the ordered member ids. Everything the operator sees
comes from that snapshot rather than from current state.

If the candidate changes before the operator answers, the review goes **stale** rather than
applying a human answer to a different question. A fresh review is raised against the new
state.

**Confirming attaches the ticket** through the same membership path automatic correlation
uses, recomputes candidate metadata, and marks any existing investigation stale — nothing
is re-run, because a model call stays the operator's decision. Other pending reviews for
that ticket close, since a report cannot belong to two mutually exclusive incidents.

**Rejecting means "not this candidate"** — not "this belongs to nothing". The ticket stays
where it was, the candidate is untouched, and any other pending review for the same ticket
stays open.

There is no authenticated identity in this prototype. Every decision is attributed to a
fixed demo operator, and the API says so in its response rather than implying a real user.

#### Labels and export

Decisions are the point as much as the attachment is. They are Northstar-native labels at
the boundary the system actually keeps getting wrong:

> Given ticket T and candidate C **as they existed at decision time**, should T be grouped
> into C?

That is not the question Polaris event labels answer, which is why M18's borrowed
supervision sat at the wrong granularity.

```bash
cd apps/api
uv run python scripts/export_correlation_labels.py
```

Writes `northstar-correlation-labels-v1` to `data/evals/labels/` — gitignored, because it
is regenerated from whatever reviews the local database holds and would otherwise publish
runtime ticket text. Features are kept separate from provenance, and an explicit forbidden
key list keeps decisions, actors, outcomes and root causes out of the feature block, so a
future model cannot train on the answer.

Two honest caveats the exporter prints itself:

- **The sample is deliberately not random.** Reviews exist only where the structural gate
  found a candidate plausible and automation declined. The base rate carries no information
  about correlation in general.
- **Nothing is retrained automatically, and a handful of clicked examples is not a
  dataset.** The exporter states how many labels exist and declines to call them
  model-ready; a supervised fallback should wait for enough independent labels to support a
  grouped train/dev/test split with hard negatives across several services and mechanisms.

**Known limitation, carried to M20.** A ticket refused by v2 stays standalone in the
window, where the stateless engine can still cluster it with a confirmed paraphrase. A
later genuine report can then land within `CANDIDATE_MARGIN` of two groupings and be called
*ambiguous* instead of attaching — it goes to review rather than into the wrong incident.
It fails toward human review rather than toward a false attachment, which makes it
something final hardening should evaluate rather than a reason to reopen correlation
semantics. Reproduced in
[test_reconciliation_v2.py](apps/api/tests/test_reconciliation_v2.py).

#### hybrid-correlation-v1, and why it is not the default

M15 left a real limitation: the deterministic baseline refuses semantically equivalent
paraphrases. `hybrid-correlation-v1` was built to address it — **selective semantic
fallback, not semantic correlation on every ticket.**

```
arriving ticket → deterministic correlation
                  ├─ attaches?        → done, no embedding
                  └─ no → is fallback justified?
                          ├─ hard conflict → done, no embedding
                          └─ eligible → embed, rescore with semantic-v1, re-check cohesion
```

**Eligibility is free**, because every condition is read from signals the deterministic
pass already produced: the candidate is inside the active window, no service / issue-type /
identifier conflict, some positive operational agreement, and — the condition that matters
— *lexical overlap is the limiting signal*. A score band was rejected: it would also fire
for tickets near the threshold for entirely different reasons, and those are not
paraphrases. Once fallback runs, scoring is exactly `semantic-correlation-v1`; hybrid
chooses *when*, never *how*, and no guardrail is relaxed.

Hybrid adds one conflict the baseline does not detect: **differing error identifiers**. The
baseline rewards a shared identifier and is silent about differing ones. That silence is a
gap here specifically — `ERR_AUTH_STALL` against `ERR_TOKEN_EXPIRED` is the most
semantically similar pair in the whole authored set, scoring *above* both genuine
paraphrases. It is detected in the hybrid gate, not in the baseline, because changing the
baseline would change results M5 and M6 already measured.

**Measured on the same 14 authored cases:**

| | deterministic | semantic-everything | hybrid |
|---|---|---|---|
| Correct outcome | **12/14** | 11/14 | **12/14** |
| False attachment | 0/9 | 0/9 | 0/9 |
| Paraphrase slice | **0/2** | **0/2** | **0/2** |
| Hard-conflict slice | 4/4 | 4/4 | 4/4 |
| Fallback invocation | — | 100% | 21.4% |
| Fast path (no embedding) | 100% | 0% | 78.6% |

**Hybrid is not the live default, because it recovers nothing.** The gate works — it fires
on exactly the right cases, for exactly the right structural reasons, and skips the
dangerous ones without cost. What fails is the signal underneath it:

| pair | cosine |
|---|---|
| genuine paraphrase | 0.66 – 0.74 |
| **conflicting-identifier case** | **0.79 – 0.80** |
| near-duplicate | 0.99 |

M6 calibrates semantic similarity from a floor of 0.72, so genuine paraphrases land *at or
below zero signal* — while the case that must never merge scores higher than either of
them. On this corpus the embedding model's similarity ordering does not track incident
identity, and lowering the floor would admit the false merge before it admitted the
paraphrase. Paying an embedding on a fifth of submissions to change no outcome is not a
trade worth making.

So the live default stays `deterministic-correlation-v1`, set in
`INCIDENTIQ_LIVE_CORRELATION_STRATEGY`. Hybrid remains implemented, evaluated, and
selectable — a recorded negative result rather than dead code.

**Latency**, warm cache: deterministic 1.33 ms, hybrid fast path 1.37 ms, hybrid fallback
6.92 ms. But an *arriving* ticket is by definition unseen, so a fallback-eligible
submission pays a real embedding: **19.3 ms marginal**, and 564 ms on the first such
submission after a restart while the model loads.

#### Embedding model bake-off

M16 ended with a specific suspicion: the fallback *gate* worked, and the embedding
*representation* did not. M17 tested whether that was the model. Same pair set, same
embedding text, same gate — only the model changed.

`Alibaba-NLP/gte-modernbert-base` and `BAAI/bge-m3` were the intended challengers and are
**not available through fastembed**; running them needs PyTorch and a Transformers version
with ModernBERT support, multiple gigabytes to answer a question two supported models can
answer. Two were substituted from *different families*, so a shared failure would say
something about the approach rather than about one model.

The measurement is **separation margin**: the weakest genuine paraphrase minus the
strongest pair that must never merge. Negative means no threshold separates them.

| model | dim | size | true paraphrase | must-not-merge | margin | ordering |
|---|---|---|---|---|---|---|
| bge-small | 384 | 0.07 GB | 0.659 – 0.740 | 0.601 – 0.804 | **−0.144** | 50.0% |
| gte-base | 768 | 0.44 GB | 0.822 – 0.880 | 0.781 – 0.886 | **−0.065** | 50.0% |
| bge-large | 1024 | 1.20 GB | 0.596 – 0.728 | 0.561 – 0.798 | **−0.202** | 54.2% |

**No model separates them.** In every one, the strongest must-not-merge pair scores higher
than the weakest true paraphrase, and ordering accuracy sits at a coin flip. A model
eighteen times the baseline's size fails *worse* than the baseline. A model from an
entirely different family fails the same way.

`gte-base` scores everything higher — 0.78 to 0.89 across the board — which is exactly the
trap: absolute cosine says nothing, and its ordering is still 50%. Near-duplicates score
~0.99 in all three and are excluded from the margin, because they already attach
deterministically; counting them would make every model look separable while the cases
that need help stayed unrecovered.

**Threshold calibration was not attempted.** Recalibrating a model whose ordering is a coin
flip cannot help, and doing it anyway would have produced a floor fitted to noise.

Phase 1 predicted the end-to-end result exactly. All three models produce **identical**
online metrics: 12/14 correct, 0% false attachment, **0/2 paraphrases recovered**, 21.4%
fallback invocation.

| model | cold load | warm embedding | p95 | embeddings/s |
|---|---|---|---|---|
| bge-small | 533 ms | 19.3 ms | 27.3 ms | 90 |
| gte-base | 447 ms | 59.2 ms | 60.3 ms | 17 |
| bge-large | 1393 ms | 55.2 ms | 56.8 ms | 20 |

**The live default stays deterministic.** No challenger earned a change: each would cost
three times the embedding latency on a fifth of submissions to recover nothing.

**What this establishes**: the problem is not the model. Generic cosine similarity over
whole-ticket embeddings is the wrong decision representation for "is this the same
incident" — it measures topical resemblance, and two tickets about the same service with
different failure mechanisms are topically near-identical. That is a property of the
question, not of a checkpoint, and swapping further general-purpose embedding models is
unlikely to change it. A discriminative approach — a pairwise classifier or a cross-encoder
trained on incident identity rather than text similarity — is the next thing worth trying,
and is outside this milestone.

#### Pairwise incident classification

M17 concluded that cosine measures topical resemblance, not incident identity. M18 models
the decision directly: *does this arriving ticket belong to this candidate?* — a small
supervised classifier over the 26 structured signals the deterministic engine already
computes, running behind the **unchanged** M16 gate so it scores exactly the slice where
cosine failed.

**Training data is the honest constraint.** The authored corpus yields about ten positives.
Polaris is the only labelled source, and its events are not incidents at this granularity:
six `launch_*` campaigns spanning 163–175 days, seven `outage_*` events spanning 3–4 days
at 200–500 tickets each, against a product window of ninety minutes and a handful of
members. Launches are excluded; outages are windowed so a training pair resembles a runtime
decision. That leaves **eight event groups** — the grouped split is correct and mandatory,
and the effective sample size for generalisation is eight however many pairs are produced.

**Negative construction took three attempts, and each failure was caught by reading
coefficients rather than accuracy**, which stayed high throughout:

1. Unaligned sampling — Polaris outages sit years apart, so the model learned
   `within_active_window` (+3.03) and scored a meaningless +0.97 separation. It had learned
   "2024 or 2026".
2. Aligning the wrong candidate to the arrival time gave negatives a zero-minute gap while
   positives had one to ninety, so it learned the inverse: `time_score_nearest` at −5.68 —
   *closer in time is less likely the same incident*.
3. Shifting the negative candidate to reproduce the positive's gap structure exactly, so
   every time feature is identical and content is the only variable.

Only the third is a real experiment. The first two would have shipped a nonsense model with
excellent metrics.

**Result: better ordering, still not separable.**

| | cosine (M17) | pairwise (M18) |
|---|---|---|
| Ordering, held-out | 50% | **74.2%** |
| Ordering, authored cases | 50% | **66.7%** |
| Separation margin, authored | −0.144 | −0.419 |
| Paraphrase recall | 0/2 | **0/2** |

Direct supervision does beat generic similarity on ordering — 50% to 74%, which is a real
signal. But on the authored cases the paraphrases score 0.27–0.43 while the
conflicting-identifier pair scores **0.689**, above both. The same failure as M17, and the
dev-selected threshold did not transfer: seven hard-negative false merges on held-out.

One learned weight is domain nonsense: `service_conflict` at **+0.375**, meaning a service
conflict makes the same incident *more* likely. That is the mismatch showing through —
Polaris `reported_category` is not a Northstar service, and within one outage different
reporters pick different categories. So this experiment cannot cleanly separate "a
discriminative model does not work" from "training on Polaris does not transfer".

**Online results are unchanged**: 12/14, 0% false attachment, 0/2 paraphrases, 21.4%
invocation — identical to deterministic and to both embedding strategies.

**The architecture held, and that is the part worth keeping.** PR04 — the pair the
classifier scored highest and must never merge — was blocked by the gate *before the model
was consulted*. The classifier is a scorer; hard conflicts and complete-link cohesion remain
the authority.

| stage | mean | p50 |
|---|---|---|
| feature extraction | 2.46 ms | 2.47 ms |
| classifier inference | **0.08 ms** | 0.08 ms |
| full ambiguous path | 5.63 ms | 5.62 ms |
| deterministic fast path | 1.26 ms | 1.26 ms |

Against the embedding fallback's 19.3 ms warm and 533–1393 ms cold load, this is far
cheaper — but cheap is not a reason to ship something that recovers nothing.

**The live default stays deterministic.** The fitted artifact is gitignored: it is trained
on CC BY-SA data, and this project flags rather than distributes anything adapted from that
corpus. `scripts/train_pairwise.py` rebuilds it; sanitised metrics carrying no Polaris
identifiers are committed.

#### What live intake will and will not group

The deterministic baseline is tuned for precision, and it shows. On the authored online
set it scores 0% false attachment and 0% missed attachment — but complete linkage means a
new report must clear the threshold against **every** existing member, and time decay
against the oldest member tightens that further as a candidate ages.

In practice a near-duplicate report attaches and a paraphrase often does not. That is the
M5 tradeoff working as measured (pairwise recall 0.2593, precision 0.875), not a defect
introduced here, and no threshold was moved to make a demo attach.

### Temporal evidence

Two incidents can end in identical current state — a deployment exists, the service is
degraded, an error signature is firing — and have opposite causal stories. Deploy at
10:04 then errors at 10:09 supports blaming the release. Errors at 09:40 then deploy at
10:04 rules it out. Before M14 those collapsed into nearly the same investigation
context, and that ambiguity was the reason IV04 and IV12 could not be told apart.

**Chronology is computed in application code, never by the model.** Subtracting
timestamps is arithmetic; a model asked to do it will usually be right, and "usually" is
not something to build a rollback argument on. The model receives the observations *and*
the derived relationships, and reasons about plausibility on top of facts it did not have
to compute.

**Incident onset** — the rule, stated once:

> Onset is the earliest **symptom**: the first error signature to begin, the first
> degraded health reading, or the first correlated ticket, whichever came first.
> A deployment is never a symptom.

That last clause is load-bearing. A candidate cause allowed to define onset precedes it by
construction — the bug that produced "deployment preceded incident onset by 0m" in M13,
and passed a vacuous policy check in M11. A regression test holds it.

**Evidence window**: onset − 60 min to onset + 30 min, with a 30-minute attribution window
inside which a deployment is still a plausible initiating cause, and a 60-second
simultaneity tolerance so clock skew is not read as sequence. All four live in
[temporal/rules.py](apps/api/app/temporal/rules.py) and are Northstar numbers, not
production defaults — a real estate would want them to vary by service and change type.

**Derived relationships** become citable evidence with system-minted ids
(`temporal:deployment_precedes_error_onset:deployment:DEP-2041:error:ERR_SAML_INVALID_ASSERTION`),
validated like any other citation. Only comparisons that bear on the two questions the
product asks are derived — could this deployment have started it, and did we see it before
the customers did — so the registry gains a handful of items rather than a quadratic pile.

**Deployment attribution** answers one narrow question: is the ordering consistent with
this release having initiated the incident? Four necessary conditions, none sufficient —
right service, precedes onset, inside the attribution window, no symptom predating it.

The wording throughout is deliberate. `temporally_compatible` never means *caused*: a
change that preceded a failure may still be unrelated, while a change that followed one
cannot have initiated it. The first is a lead; only the second is dispositive. Verdicts
belong to the model, and are labelled as its opinion wherever they appear.

Health is now an authored **sequence** rather than one snapshot. One reading answers "is
it broken"; it cannot answer "was it fine before that deployment shipped", and that second
question is the whole difference between a release that plausibly caused an incident and
one that merely happened nearby.

**Cost**: deriving the whole chronology takes 0.062 ms — against 73.8 ms for evidence
collection overall, which is dominated by retrieval. Eight relationships are derived where
the naive all-pairs ceiling would be 64, because only the comparisons the product asks
about are computed.

All of it is synthetic. These are authored Northstar observations with hand-written event
times, not a feed from any monitoring system. Real telemetry is noisier, arrives late, and
disagrees with itself; nothing here has been tested against that.

### Durable investigations

An investigation is a record, not a function call. `POST` creates one; every `GET` reads
what was stored. Loading an incident page used to cost about eleven seconds and a set of
tokens, and a reload could return a different answer than the one the operator was
reading a moment earlier — a page render is now free and idempotent.

Each run stores **the exact evidence it was shown**, as JSONB, and is immutable once it
reaches `succeeded` or `failed`. It also records which *evidence contract* it was given —
`evidence-v1` for everything before M14, `evidence-v2` for runs with temporal evidence —
alongside the temporal window configuration in force. Temporal evidence is never
backfilled onto a historical run: a run recorded under v1 stays v1, so two runs that
disagree can be explained by what each was shown rather than guessed at. Re-investigating inserts a new run and leaves every
earlier one untouched, so "what did investigator-v2 see when it recommended this
rollback" stays answerable after the operational world has moved on. An action links to
the run that recommended it and is never repointed at a newer one.

A failed re-run is kept and does not hide the last successful answer. Two concurrent
requests cannot both call the model: a partial unique index on `(incident_id)` where the
status is pending or running means the second request is handed the run already in
flight.

### Historical retrieval on pgvector

Retrieval moved into PostgreSQL. **Not because 40 ms was slow** — it was not, and the
measurements below say so. The reasons are architectural: PostgreSQL is now required for
workflow state regardless; vectors survive a restart, so the API no longer rebuilds a
corpus index at startup or holds every vector in memory; adding a historical incident
becomes an `INSERT` rather than a rebuild; and ranking plus metadata filtering happen in
one query.

M7 ranks on `0.80·cosine + 0.08·service_overlap + 0.12·error_overlap`, not raw cosine, so
ordering by vector distance alone would have quietly changed what the product returns.
The whole expression is computed in one SQL statement instead — pgvector for the cosine
term, array intersection for the overlaps, over tokens normalised at import by the same
Python function the in-memory index used. A test asserts the two implementations return
identical ids and scores.

| | build | mean | p50 | p95 |
|---|---|---|---|---|
| In-memory index (M7) | ~75 s cold, 0.06 s warm cache | 37.9 ms | 37.5 ms | 41.0 ms |
| pgvector exact | none — already in the database | 29.8 ms | 30.2 ms | 34.9 ms |
| pgvector + HNSW | 0.1 s index build | 28.0 ms | 27.5 ms | 31.9 ms |

751 records, 384 dimensions. About 13.6 ms of every row above is embedding the query,
which all three pay equally.

**Exact search is used; there is no ANN index.** HNSW saved 1.8 ms — roughly 6%, inside
the noise — in exchange for an approximate recall tradeoff and an index to maintain. That
is not a trade worth making at 751 rows. ANN can be introduced when corpus scale warrants
it, and the measurement above is what should be repeated to decide.

The in-memory `HistoricalIndex` remains in `app/retrieval/index.py` as a **reference
implementation** for regression comparison and offline evaluation. It is not reachable
from any request path — there is one runtime retrieval implementation, not two that
something might choose between.

pgvector did not make retrieval *better*; retrieval quality is unchanged, by design and by
test. It made the system durable.

### Investigation and the model

Investigation calls OpenAI's Responses API with structured outputs, via the official
Python SDK. Credentials come from `OPENAI_API_KEY` in the environment or a gitignored
`apps/api/.env` — nothing is stored in the repository. The model is configurable with
`INCIDENTIQ_INVESTIGATION_MODEL` and defaults to `gpt-5.6-terra`. **Without credentials
the investigation endpoint returns a 503 explaining what to configure**; triage,
correlation and retrieval are unaffected, and no investigation is ever fabricated.

Structured outputs guarantee the *shape* of the answer, not its truth — which is why
every result still passes application-side validation.

**Remediation is gated, not automatic.** A model recommendation passes deterministic
policy — action-specific since `action-policy-v2`, described below — before a human may
approve it, and approval and
execution are separate clicks. Execution is **simulated** — no infrastructure is
contacted — and every boundary is audited with precise actor attribution: the model
recommends, the system proposes and executes, a human approves. Action state is
in-memory and resets when the API restarts.

Measured once on the 16 authored held-out cases (`gpt-5.6-terra`, 2026-08-27): 100%
leading-hypothesis accuracy, 75% abstention accuracy, 0% unsupported citations, 0%
unsupported remediation, against a retrieval-only baseline of 83.3% / 37.5%. The abstain
decision varies between runs — see the evaluation reference for the caveat.

#### Evidence of failure is not evidence for an action

`action-policy-v1` asked one question of every action: are there at least two independent
kinds of evidence? Measuring investigator-v2 showed why that is not enough. Three
`restart_service` recommendations passed it on services that were degraded and emitting
errors — every generic check green — with nothing establishing that a restart addressed
what was actually broken. Counting evidence answers *how much*; the question was *of what*.

`action-policy-v2` asks each action its own questions, all of them plain predicates over
typed fixture records:

**rollback_deployment** — the cited deployment matches a real record; it shipped *before*
onset and within a two-hour blast window; the service degraded *after* it and was not
already degraded before; there is an error signature on the changed service; and nothing
points at a cause a rollback cannot reach.

**restart_service** — the service is genuinely unhealthy; an error signature indicates the
wedged process state a restart clears (a closed error-code → failure-mechanism table in
[mechanisms.py](apps/api/app/actions/mechanisms.py), never a grep over log prose); no
configuration, credential, permission, data or dependency failure is implicated, since
those survive a restart untouched; and no recent release better explains the degradation,
which would make rollback the right action instead. An unclassified error code is
`UNKNOWN` and does **not** satisfy restart relevance — a new code makes restarts harder to
approve until somebody classifies it, which is the correct direction to fail.

Onset is derived from symptom evidence only. Letting the suspected deployment set it would
make "the release came before the trouble" true by construction with a gap of zero.

Every check names the evidence it read, so a rejection is traceable rather than asserted.
`action-policy-v1` is preserved unchanged in `policy.py` — the recorded M9 results are
attributable to it, and a superseded policy that quietly changes is a benchmark that lies.

#### The v1 → v2 remediation experiment

`investigation-v1` scored 0% unsupported remediation because it recommended remediation
on **zero** of the six cases where an action was justified. That is not caution, it is
the workflow not working: the approval and execution machinery had nothing to receive.

v1 never told the model what happens to a recommendation, and the model appeared to treat
"recommend a rollback" as "authorize a rollback". `investigation-v2` (`prompt_v2.py`)
changes exactly that: it states that a recommendation is a proposal screened by
deterministic policy and approved by a human, and it separates "is there a diagnosis?"
from "is there a supported action?". Every v1 safety clause is carried over verbatim and
no application-side validation changed. v1 is frozen and hash-pinned by a test.

Both prompts, run once each on the same held-out cases:

| | v1 | v2 |
|---|---|---|
| Remediation recall | 0% (0/6) | **100% (6/6)** |
| Policy-eligible remediation recall | 0% | **100%** |
| Remediation precision | undefined | 66.7% (6/9) |
| Unsupported remediation rate | 0% | **18.8% (3/16)** |
| Leading-hypothesis accuracy | 100% | 100% |
| Abstention accuracy | 75% / 68.8% (two runs) | 68.8% |
| Unsupported citation rate | 0% | 0% |

**The cost is real, and action-specific policy does not absorb it either.** Replaying the
recorded v2 recommendations through `action-policy-v2` blocks none of them: all three
restarts land on svc-connector, whose `ERR_SYNC_STALLED` signature ("sync worker heartbeat
missed; job left in running state") *is* the wedged-worker mechanism a restart addresses.
Policy is right not to block them. What was wrong in those cases was the model concluding
at all rather than the action it chose — a diagnosis failure, which a gate on action
support is not the place to fix.

Where policy-v2 does separate from v1 is on cases this particular run did not contain, and
the authored matrix in [test_policy_v2.py](apps/api/tests/test_policy_v2.py) covers them: a
restart against a configuration or credential failure, against a healthy service, against a
recent release that better explains the degradation; a rollback of a deployment that
predates onset by days, or that shipped after the service was already degraded, or where
the errors point at a dependency. `action-policy-v1` allowed every one of those.

#### Evaluation versions

**A number belongs to the evidence contract it was measured under.** eval-v3 supplies
temporal evidence that v1 and v2 runs never saw, so a v3 metric and a v2 metric answer
different questions. Comparing them as though only the model changed would be the central
mistake this milestone is set up to avoid — the prompt did not change at all.


`investigation-eval-v1` (`investigation_cases.json` / `investigation_labels.json`) is
frozen and hash-pinned by a test; every recorded metric stays attributable to it.

`investigation-eval-v2` carries all sixteen v1 cases over byte-for-byte and changes two
things. It adds IV17–IV19 so the restart boundary has cases on both sides of it, and it
adjudicates a real inconsistency: **IV04 and IV12 sit on the same service minutes apart, so
evidence collection hands them identical operational signals, yet v1 labelled a restart
unsupported on one and correct on the other.** The difference was ticket quality, not
evidence. v2 keeps the differing *diagnosis* expectation — IV04's single vague ticket
supports no conclusion — but adds `remediation_unsafe` to stop scoring the action itself as
dangerous. IV03, IV07 and IV08 share that service and evidence and were adjudicated the
same way, because fixing one and not the others would trade one inconsistency for another.

The remaining `remediation_unsafe` cases are the ones where acting would genuinely do harm:
a healthy service, or no identified service at all.

`investigation-eval-v3` carries every v2 case forward and changes exactly two things. It
adds `operations` blocks to **IV04 and IV12**, and it adds TC01–TC08, eight original cases
that probe causal order specifically: a release before the errors and a release after them,
a release ten hours stale, two releases with only one in the window, a wedged worker with
no release at all, a credential failure following a configuration change, an external
dependency failing first, and reports arriving two hours after the machine noticed.

**IV04 and IV12 are separated by evidence, not by relabelling.** They were
indistinguishable for a structural reason: evidence collection is service-scoped, both are
`svc-connector`, and so both received byte-identical operational signals however
differently their tickets read. No adjudication of labels could fix that. In eval-v3 they
carry their own authored chronologies:

| | IV12 | IV04 |
|---|---|---|
| 12:20 | healthy | healthy |
| 12:41 | `ERR_SYNC_STALLED` begins | — |
| 12:58 | — | `DEP-2051` ships, rotating a credential reference |
| 13:02 | — | `ERR_TOKEN_EXPIRED` begins |
| 13:20 | degraded | degraded |
| Deployment in window | none — the only release is 9h earlier | yes, 4 minutes before onset |
| Failure mechanism | wedged worker | credential |

Different mechanism, different deployment proximity, different ordering. Neither block
states which action is correct — a test asserts the words "restart" and "rollback" appear
in neither.

#### eval-v3 result

One run, `gpt-5.6-terra`, prompt `investigation-v2` **unchanged**, evidence-v2, 27 cases.
The prompt did not move; only the evidence did.

| | |
|---|---|
| Deployment attribution accuracy | **100% (8/8)** |
| Leading-hypothesis accuracy | 100% (15/15) |
| Top-3 accuracy | 100% (15/15) |
| Remediation recall | 100% (13/13) |
| Policy-eligible recall | 100% (13/13) |
| Remediation precision | 76.5% (13/17) |
| Abstention accuracy | 74.1% (20/27) |
| Structured-output validity | 92.6% (25/27) |
| Unsupported citations | 7.4% (2/27) |
| Unsupported remediation | 14.8% (4/27) |

**These are not comparable to the eval-v2 numbers.** Different cases, and — more
importantly — different evidence. That is the point of versioning both.

**The question this milestone actually asked** was whether explicit chronology resolves
cases that were observationally indistinguishable. It did:

- **IV04 → `rollback_deployment`**, where under eval-v2 it recommended `restart_service`.
  Given a configuration change four minutes before a credential failure, the model stopped
  proposing a restart and named the release.
- **IV12 → `restart_service`**, unchanged. Wedged worker, no release in the window.
- **TC02, the causality trap** — errors 24 minutes *before* the deployment — produced **no
  remediation**. The model did not blame the later release.
- **TC06**, external dependency failing first: no remediation.
- TC01, TC05, TC07 correctly named the release; TC08 correctly chose restart.

Two complications, neither patched after the fact:

**IV04's label is now questionable for its own evidence.** It was authored as "one vague
ticket, nothing to conclude" and carries `expect_abstain: true`. eval-v3 gave it a clear
chronology, and on that chronology answering is defensible — so the model is scored wrong
twice (abstention, unsupported remediation) for behaviour that may be correct. Enriching
the evidence changed what the right answer is. The label has not been adjusted, because
adjusting it after seeing the result is exactly the move that makes a benchmark
meaningless.

**TC03 and TC04 failed structured-output validation** because the model truncated a
111-character evidence id. Relationship ids were composed from two full evidence ids, and
a health evidence id embeds an ISO timestamp — colons inside a colon-delimited id. The
guardrail worked: the citations were rejected rather than accepted. The id scheme has
since been shortened to under 80 characters with a test enforcing it, **and that fix is
unmeasured** — it landed after the official run, and re-running to collect a nicer number
would defeat the one-run discipline.

**IV17–IV19 have never been run against any model.** They were authored in eval-v2 to test
the policy boundary and no investigator has been scored on them. Any metric including them
is a first measurement under eval-v3, and nothing should read as though they were part of
an earlier result.

What the model is and is not trusted with:

- It sees only evidence this system collected, each item carrying an id.
- Every hypothesis and every remediation recommendation must cite those ids. A citation
  the registry does not recognise fails validation and the result is rejected — the
  operator gets nothing rather than an ungrounded claim.
- Abstaining and recommending remediation are mutually exclusive, enforced in code.
- Action types are closed enums, so an action the product has no notion of cannot be
  invented.
- Ticket text and historical records are fenced as data in the prompt, and the model is
  told not to follow instructions found inside them.

Confidence shown in the UI is the model's own estimate. It is not calibrated and is
labelled as such wherever it appears.

### Embeddings

`semantic-correlation-v1` embeds ticket title and description with
`BAAI/bge-small-en-v1.5` running locally through fastembed (ONNX, CPU, no PyTorch). No
API key and no per-call cost, which is what makes the comparison reproducible on any
machine; the model downloads once on first use. Vectors are cached under
`data/processed/embeddings/` — gitignored, keyed by provider and model so vectors from
one model can never be reused by another.

The embedding is **one signal among five**. It cannot merge tickets across a service
conflict or a time gap on its own, and when the provider is unavailable the semantic
endpoints fail with a configuration error rather than quietly returning baseline
results.

**Dev/test split.** The authored golden sets in `data/evals/golden/` (triage) and
`data/evals/correlation/` (correlation) are the development sets: rules are iterated
against them. Polaris is held out — it is run to measure, not to tune. Retuning rules
against its labels would turn a benchmark into training data, so the numbers it produces
are reported as they come.

**Precision over recall in correlation.** A false merge invents a major incident that is
not happening and sends people chasing it; a missed correlation leaves a ticket where it
already was. Thresholds are set on the strict side and false-merge rate is reported next
to recall.

## Data and licensing

**Northstar Cloud is a fictional organisation.** Every record the API serves today is
fabricated and was authored specifically for IncidentIQ — see
[data/demo/northstar_cloud/README.md](data/demo/northstar_cloud/README.md). No external
dataset has been ingested yet.

External datasets are license-reviewed before use, and the CC BY-SA Polaris dataset is
never committed to this repository. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
