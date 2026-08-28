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
| `POST /correlation/candidates/{id}/investigate` | evidence-backed AI investigation (requires `OPENAI_API_KEY`) |
| `GET /evals/investigation` | investigation metrics (`?version=v1`, `v2` or `baseline`) |
| `POST /incidents/{id}/actions` | propose an action from a remediation recommendation |
| `GET /incidents/{id}/actions` | actions proposed for an incident |
| `POST /actions/{id}/approve` | explicit human approval |
| `POST /actions/{id}/reject` | explicit human rejection |
| `POST /actions/{id}/execute` | run the simulated action (idempotent) |
| `GET /actions/{id}/audit` | the action's audit trail |
| `GET /evals/policy` | action-policy suite results |
| `GET /evals/policy/replay` | policy-v1 versus policy-v2 on identical recorded recommendations |

Both correlation endpoints take `?mode=deterministic` (the default) or `?mode=semantic`,
and `/evals/correlation` takes `?version=`. The version is stamped on every response.

Records come from the fixture directory in `data/demo/northstar_cloud`, loaded and
validated at startup. There is no database yet.

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

## Checks

```bash
cd apps/api && uv run pytest      # backend tests
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
- **`semantic-correlation-v1`** — the same correlation with one extra signal: cosine
  similarity between ticket embeddings. Same candidate generation, same guardrails, so
  the two are directly comparable. Opt-in everywhere; deterministic stays the default.
- **`historical-retrieval-v1`** — given a current incident, finds resolved incidents that
  looked like it, and shows what those turned out to be. Retrieval matches *symptoms
  only*; a historical cause and fix are displayed after a match, never used to make one.
- **`investigation-v1`** — the only place a language model runs. It receives a fixed set
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
