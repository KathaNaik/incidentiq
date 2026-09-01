# Northstar Cloud — world v2 design

**Status: FROZEN.** Authored ground truth for the expanded Northstar Cloud demo world.

This document was completed **before** any expanded fixture record was written and before
the world was run through correlation. That ordering is the point. Authoring a ticket,
scoring it, seeing 0.57 and rewriting the sentence until it reads 0.61 produces a dataset
that proves the system works because it was built to.

Once frozen, the following may **not** be changed in response to runtime results: incident
truth, ticket allocation, hard-negative meaning, boundary labels, chronology, or ticket
wording. Typos, malformed JSON, invalid foreign keys, schema violations and genuine
implementation defects may be fixed. A low correlation score may not.

---

## 1. What this task does not touch

**Northstar World v2 does not modify `ERROR_MECHANISMS` or action-policy semantics.**

An earlier draft of this design proposed classifying eight new error codes. That is
withdrawn. `ERROR_MECHANISMS` decides whether a mechanism is restart-addressable or
restart-contraindicated, and adding a mapping changes whether an action becomes
policy-eligible. That is a policy semantic change wearing dataset clothing.

Every new error code introduced by this world therefore classifies as `UNKNOWN`, and the
consequences are accepted as realistic:

- symptoms may look restart-like to a reader
- the investigator may discuss a restart if the evidence supports one
- deterministic policy does **not** treat the mechanism as established
- the action may remain blocked or require stronger evidence

The existing connector scenario (`ERR_SYNC_STALLED` → `TRANSIENT_RUNTIME`) already
demonstrates a restart-addressable case. The world does not need a second one badly enough
to justify editing a policy table.

Also unchanged: correlation weights and thresholds, `deterministic-correlation-v1`/`v2`,
review eligibility and semantics, investigation prompts, embedding and pairwise models,
temporal reasoning, policy-v2, execution behaviour, deployment architecture, and every
historical eval artifact.

---

## 2. Timestamp and replay strategy

### Mechanics, measured not assumed

| Property | Value | Source |
|---|---|---|
| Authored timestamps | fixed, literal | `seed_tickets.py` writes fixture `created_at` verbatim to both `created_at` and `received_at` |
| Wall-clock remapping | **none** | no offset is applied at seed time |
| `REPLAY_WINDOW` | 6 hours | `CANDIDATE_IDLE_MINUTES × 4` |
| Practical pair-link ceiling | **~61 minutes** | `TIME_HALF_LIFE=20`, `TIME_LINK_MIN=0.12`; 60 min → 0.125, 75 min → 0.074 |
| Candidate idle close | 90 minutes | `CANDIDATE_IDLE_MINUTES` |

None of these is being changed. The world is designed around them.

### Design rules that follow

1. **Inside an incident**, consecutive reports sit **≤ 40 minutes apart** — comfortably
   inside the linking regime, so grouping is decided by content rather than by scraping
   past a time floor.
2. **Same-service incidents that must stay distinct** are separated by **≥ 120 minutes**
   between the earlier one's last activity and the later one's first symptom. The original
   draft used exactly 90 minutes, which placed authored ground truth precisely on a
   lifecycle boundary and made the world depend on `<` versus `<=`. Corrected.
3. **No important case is authored near the ~61-minute pair-link edge.** Ground truth
   should be established clearly, not balanced on threshold behaviour.

### Waves

The world is organised into three operational waves rather than one giant concurrent
outage. Within a wave incidents genuinely overlap and reports must compete between several
plausible candidates; across waves, events fall naturally outside each other's correlation
activity.

| Wave | When | Contents |
|---|---|---|
| **A** | 2026-08-24, 08:40–09:45 | The existing hero (`INC-1042`). **Frozen, untouched.** |
| — | 2026-08-25, 12:20–16:05 | Existing connector incident (`INC-1043`) and existing isolated tickets. Untouched. |
| **B** | 2026-08-26, 08:40–11:25 | Five incidents overlapping across five services |
| **C** | 2026-08-26, 13:35–16:05 | Three incidents, including the deployment-after-symptoms counterexample |

Wave B's last activity is 11:20; wave C's first symptom is 13:35 — **135 minutes** of
margin. The two analytics incidents (N3 in wave B, N4 in wave C) are **225 minutes** apart.

---

## 3. Known limitation: current-day intake cannot reach the authored world

**Question:** can an API-submitted ticket whose `created_at` is the real current date
correlate against the fixed authored world?

**Answer: no.** Intake selects its replay window as
`[arriving.created_at − 6h, arriving.created_at]`. A ticket submitted today sees only
tickets from the preceding six hours of *today*. The authored world lives on 2026-08-24 to
2026-08-26. The window is empty of it, so a current-day report is always `uncorrelated` and
creates its own candidate.

To exercise correlation, a submitted ticket must carry a `created_at` inside an authored
wave — which is exactly what the M20 acceptance runs did.

**This is recorded, not fixed.** Introducing timestamp remapping or widening the replay
window are both real options, and both are correlation-configuration changes that this task
is explicitly forbidden to make. Fixing it here would also contaminate the dataset work: the
world would then be designed against a moving target. It belongs in its own change.

---

## 4. Incident matrix

Nine incident stories. **Four involve no deployment at all**, one has a deployment that
arrives after symptoms, and two are clean deployment attributions. If every incident implied
a rollback, the product would only ever demonstrate one answer.

| Incident | Service | Wave | Mechanism | Deployment | Reports | State | Causal shape |
|---|---|---|---|---|---:|---|---|
| `INC-1042` | svc-auth | A | SAML config regression | `DEP-2041` **causal** | 5 | monitoring | clean attribution *(frozen)* |
| `INC-1043` | svc-connector | — | sync worker wedged | `DEP-2044` unrelated | 3 | investigating | transient runtime *(frozen)* |
| `INC-1044` | svc-auth | B | upstream IdP latency | **none** | 5 | resolved | external dependency |
| `INC-1045` | svc-analytics | B | ingestion consumer backlog | **none** | 4 | active | backlog / runtime |
| `INC-1046` | svc-analytics | C | dashboard cache serving empties | **none** | 4 | active | same service as 1045, different mechanism |
| `INC-1047` | svc-billing | B | payment provider latency → retry storm | **none** | 4 | active | external dependency |
| `INC-1048` | svc-api | B | release introduces upstream timeout path | `DEP-2047` **causal** | 4 | active | clean attribution |
| `INC-1049` | svc-notifications | B | email provider degradation | **none** | 4 | resolved | external dependency |
| `INC-1050` | svc-search | C | index queue backlog | `DEP-2048` **after symptoms** | 4 | active | counterexample |
| `INC-1051` | svc-files | C | processing worker wedged | **none** | 4 | active | runtime, `UNKNOWN` mechanism |

---

## 5. Service catalogue — 8

| Service | Name | Role | Status |
|---|---|---|---|
| `svc-auth` | Authentication | SSO, sessions, API token exchange | existing |
| `svc-analytics` | Analytics Dashboard | dashboards, saved reports, exports | existing |
| `svc-connector` | Connector API | warehouse sync | existing |
| `svc-api` | Public API | customer-facing API gateway | **new** |
| `svc-billing` | Billing | invoicing, payment provider webhooks | **new** |
| `svc-notifications` | Notifications | transactional email and alerts | **new** |
| `svc-search` | Search | indexing and query | **new** |
| `svc-files` | File Processing | uploads, conversion, scanning | **new** |

Admin and permissions cases are deliberately **not** a separate service. They live on
`svc-auth`, where they are a far stronger hard negative: same service, same vocabulary,
entirely different mechanism.

---

## 6. Frozen chronologies

Operational evidence records *what happened when*. It never encodes a conclusion such as
"rollback is correct" — that inference is the investigator's job and the policy's check.

### INC-1044 — auth, upstream identity provider *(no deployment)*
```
08:35  svc-auth healthy
08:40  upstream IdP latency rises        ERR_IDP_LATENCY (UNKNOWN)
08:47  svc-auth degraded
08:52  first report
09:28  last report
10:10  svc-auth healthy again            resolved
```
No svc-auth deployment anywhere in the window. Ground truth: **an external dependency
degraded; nothing shipped.** A rollback has nothing to roll back to.

### INC-1045 — analytics ingestion backlog *(no deployment)*
```
08:55  svc-analytics healthy
09:00  ingestion consumer falls behind   ERR_INGESTION_LAG (UNKNOWN)
09:12  svc-analytics degraded
09:05  first report
09:50  last report
```
Ground truth: **backlog, no change event.** Dashboards serve stale but correct data.

### INC-1046 — analytics dashboard cache *(no deployment, wave C)*
```
13:30  svc-analytics healthy
13:32  cache layer returns empty payloads  ERR_CACHE_EMPTY_PAYLOAD (UNKNOWN)
13:41  svc-analytics degraded
13:35  first report
14:12  last report
```
Ground truth: **same service as INC-1045, unrelated mechanism.** The underlying data is
current; the presentation layer is wrong. 225 minutes after INC-1045's last report.

### INC-1047 — billing webhook retry storm *(no deployment)*
```
09:30  svc-billing healthy
09:35  payment provider latency rises    ERR_WEBHOOK_RETRY (UNKNOWN)
09:47  svc-billing degraded
09:40  first report
10:22  last report
```
Ground truth: **external provider; retries amplify the symptom.**

### INC-1048 — API 5xx after release *(clean deployment attribution)*
```
10:15  svc-api healthy
10:30  DEP-2047 svc-api 5.2.0 deployed
10:34  ERR_API_5XX_SPIKE begins          (UNKNOWN)
10:38  svc-api degraded
10:52  svc-api critical
10:44  first report
11:20  last report
```
Ground truth: **the deployment is temporally plausible as the initiating change** — healthy
before, errors four minutes after, degradation only afterwards. Second clean attribution in
the world, on a different service from the hero.

### INC-1049 — notification delivery delays *(no deployment)*
```
09:52  svc-notifications healthy
09:58  email provider degradation        ERR_DELIVERY_DELAY (UNKNOWN)
10:11  svc-notifications degraded
10:05  first report
10:48  last report
11:30  svc-notifications healthy again   resolved
```
Ground truth: **external provider; messages queue rather than fail.**

### INC-1050 — search index backlog *(deployment AFTER symptoms — counterexample)*
```
14:10  svc-search healthy
14:20  ERR_INDEX_BACKLOG begins          (UNKNOWN)
14:26  svc-search degraded
14:32  first report
14:55  DEP-2048 svc-search 3.1.1 deployed   ← after degradation
15:08  last report
```
Ground truth: **the deployment cannot be the initiating cause.** The service was already
degraded before it shipped. Policy-v2 already requires degradation *after* a deployment and
none before, so this should fail rollback support on the evidence rather than on a rule
written for this case.

### INC-1051 — file processing worker stall *(no deployment)*
```
15:10  svc-files healthy
15:15  ERR_PROCESSING_STALL begins       (UNKNOWN — deliberately unclassified)
15:22  svc-files degraded
15:25  first report
16:02  last report
```
Ground truth: **the worker is alive and accepting uploads but completing nothing.** Reads
as restart-shaped to a human. Because the code is `UNKNOWN`, policy will not treat the
mechanism as established — recorded as expected behaviour, not a defect.

### Unrelated deployments — no incident follows

| Deployment | Service | When | Note |
|---|---|---|---|
| `DEP-2045` | svc-notifications | 2026-08-26 07:10 | routine, healthy throughout |
| `DEP-2046` | svc-search | 2026-08-26 08:20 | routine, six hours before INC-1050 |
| `DEP-2049` | svc-billing | 2026-08-26 12:05 | routine, after INC-1047 began |
| `DEP-2050` | svc-api | 2026-08-26 16:40 | routine, after everything |

Not every deployment causes an incident. Without these the temporal machinery would never
have to reject a candidate change.

---

## 7. Ticket perspectives — frozen before prose

Reporter and observation are fixed here. Final wording is written from these, so lexical
diversity emerges from **who is speaking** rather than from deliberate paraphrase
engineering. Wording is not revised afterwards on the basis of any score.

### INC-1044 — auth, upstream IdP (wave B)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4201 | 08:52 | support engineer | sign-in takes 30+ seconds, sometimes times out |
| TKT-4202 | 09:04 | customer success | a customer's team is retrying login repeatedly |
| TKT-4203 | 09:15 | SRE on call | auth latency graph climbing, no release today |
| TKT-4204 | 09:22 | end user | "it works on the second try" |
| TKT-4205 | 09:28 | account manager | enterprise customer asking if there is an outage |

### INC-1045 — analytics ingestion (wave B)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4211 | 09:05 | marketing analyst | today's numbers stopped moving |
| TKT-4212 | 09:24 | data engineer | events accepted at the API but not in dashboards |
| TKT-4213 | 09:38 | executive assistant | scheduled morning report shows yesterday's totals |
| TKT-4214 | 09:50 | product manager | funnel chart missing the last few hours |

### INC-1046 — analytics cache (wave C)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4221 | 13:35 | sales ops | dashboard opens completely blank |
| TKT-4222 | 13:52 | analyst | charts empty, but CSV export has the right data |
| TKT-4223 | 14:04 | support engineer | reloading fixes it for some users, not others |
| TKT-4224 | 14:12 | customer | widgets show a spinner forever |

### INC-1047 — billing webhooks (wave B)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4231 | 09:40 | finance ops | payment confirmations arriving late |
| TKT-4232 | 09:58 | customer | charged, but the invoice still says pending |
| TKT-4233 | 10:10 | integration engineer | receiving the same webhook several times |
| TKT-4234 | 10:22 | support engineer | subscription status lagging behind the provider |

### INC-1048 — API 5xx (wave B)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4241 | 10:44 | API consumer | requests failing with server errors |
| TKT-4242 | 10:57 | partner developer | integration retry loop, roughly one in three fails |
| TKT-4243 | 11:09 | SRE on call | error rate spike right after this morning's release |
| TKT-4244 | 11:20 | customer engineer | webhook endpoint returning 500s to their platform |

### INC-1049 — notifications (wave B)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4251 | 10:05 | support engineer | password reset mail taking 20 minutes |
| TKT-4252 | 10:19 | end user | never received the invitation email |
| TKT-4253 | 10:34 | SRE on call | alert notifications delayed, none bouncing |
| TKT-4254 | 10:48 | customer success | onboarding emails arriving out of order |

### INC-1050 — search backlog (wave C)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4261 | 14:32 | content manager | new documents not appearing in search |
| TKT-4262 | 14:44 | end user | can find old files, not the one uploaded today |
| TKT-4263 | 14:56 | support engineer | search returns stale results for recent objects |
| TKT-4264 | 15:08 | data engineer | index lag growing, queries themselves are fine |

### INC-1051 — file processing (wave C)
| ID | Time | Perspective | Observation |
|---|---|---|---|
| TKT-4271 | 15:25 | end user | upload finishes then nothing happens |
| TKT-4272 | 15:38 | support engineer | files stuck in processing for over an hour |
| TKT-4273 | 15:50 | customer | document never becomes available after upload |
| TKT-4274 | 16:02 | ops engineer | processing queue depth climbing, no errors surfaced |

---

## 8. Hard negatives — frozen pairings

Same service, overlapping vocabulary, genuinely different mechanism. Decided here, before
correlation sees any of them.

| ID | Superficially resembles | Why it is actually different |
|---|---|---|
| TKT-4301 | INC-1044 (auth degradation) | Admin cannot save an SSO role mapping. Control-plane **permissions/configuration**, not authentication availability. Sign-in works. |
| TKT-4302 | INC-1045 (ingestion lag) | User set the date filter to last month. **Single-user configuration**; source metrics are current and healthy. |
| TKT-4303 | INC-1047 (webhook storm) | One invoice has the wrong tax rate. **Billing configuration** for one account, not delivery or provider latency. |
| TKT-4304 | INC-1048 (API 5xx) | Client is using a revoked API key and gets 401s. **Authentication**, not server errors. |
| TKT-4305 | INC-1050 (index backlog) | User's query syntax does not match what they expect. **Query construction**, indexing is current. |
| TKT-4306 | INC-1051 (processing stall) | One upload rejected — unsupported file type. **Input validation**, not a wedged worker. |
| TKT-4307 | INC-1049 (delivery delays) | Notification preferences disabled for that user. **User setting**, mail was never sent. |

### Ordinary support traffic — no incident, no near-miss

`TKT-4308`–`TKT-4314`: forgotten password · proration question · SSO metadata question from
a prospective customer · rate-limit question · a saved report the user deleted themselves ·
scheduled-export timezone confusion · a browser-specific rendering complaint.

**14 isolated reports total** (7 hard negatives + 7 ordinary).

---

## 9. Boundary cases — frozen truth

Genuinely near the decision boundary: same service, compatible timing, no hard conflict,
wording substantially different from the incident's other reports.

**The intended answer lives only here.** It is not encoded in the ticket text, and no
operator decision is pre-created by seeding — the queue must generate these through the
existing `ReviewService`, exactly as runtime intake does.

| ID | Time | Candidate(s) | Observable evidence | Truth | Justification |
|---|---|---|---|---|---|
| TKT-4401 | 09:10 | INC-1044 | "console hangs on the loading spinner after entering credentials" | **SAME** | The IdP timeout as seen by someone who never reached an error message. Same mechanism, no shared vocabulary. |
| TKT-4402 | 09:18 | INC-1044 | "my session expired mid-morning and I had to sign in again" | **DIFFERENT** | Ordinary token expiry for one user. Coincidental timing; auth availability is irrelevant to it. |
| TKT-4403 | 09:33 | INC-1045 | "the weekly summary is showing Tuesday's figures" | **SAME** | Stale data from the ingestion backlog, described by output rather than cause. |
| TKT-4404 | 13:58 | INC-1045 **or** INC-1046 | "our numbers look wrong on the overview page" | **AMBIGUOUS / INSUFFICIENT EVIDENCE** | Genuinely undecidable from what the reporter wrote. "Wrong numbers" fits both a stale-data backlog and an empty-cache render. The report contains nothing that separates them. |
| TKT-4405 | 10:14 | INC-1047 | "we were billed twice for the same seat upgrade" | **SAME** | Duplicate webhook delivery seen from the customer's side. |
| TKT-4406 | 10:30 | INC-1047 | "we are disputing a charge from last quarter" | **DIFFERENT** | A real commercial dispute about a historical charge. Nothing to do with today's delivery latency. |
| TKT-4407 | 11:02 | INC-1048 | "the integration is flaky this morning, some calls just do not come back" | **SAME** | The 5xx spike as experienced by a partner who never saw a status code. |
| TKT-4408 | 10:40 | INC-1049 | "one of our admins never got her invite" | **SAME** | Sounds individual, is the delivery backlog. Deliberately the shape support triages wrongly. |
| TKT-4409 | 14:50 | INC-1050 | "I cannot see the folder a colleague says they shared" | **DIFFERENT** | Sharing permissions, not indexing. The object is findable by someone with access. |
| TKT-4410 | 15:44 | INC-1051 | "the progress bar sits at 99% and stays there" | **SAME** | The wedged worker, described by UI state. |

**Distribution: 6 SAME · 3 DIFFERENT · 1 AMBIGUOUS.**

On `TKT-4404`: no binary answer is forced. Expected product behaviour is that the available
observable information is insufficient to safely assign candidate A or B, and the honest
outcomes are review or standalone. This case exists to test abstention rather than to
pretend all ticket grouping has knowable ground truth.

---

## 10. Data distribution

| Category | Existing | New | Total |
|---|---:|---:|---:|
| Incident-associated | 8 | 33 | 41 |
| Isolated / support traffic | 3 | 14 | 17 |
| Boundary cases | 0 | 10 | 10 |
| **Tickets** | **11** | **57** | **68** |

Six of the ten boundary reports are intended `SAME`, so they genuinely belong to incidents
as well. They are counted once, in the boundary row, rather than double-counted to inflate
the incident-associated total.

| | Now | Planned |
|---|---:|---:|
| Services | 3 | 8 |
| Incidents | 2 | 11 |
| Deployments | 4 | 10 |
| Health observations | 8 | ~40 |
| Error records | 4 | ~18 |
| Authored precedents | 6 | ≤9 |

---

## 11. Hero preservation contract

Regression checklist. Every item is verified after authoring.

- `TKT-4101`–`TKT-4105` — ids, titles, descriptions, timestamps, service, priority
- `INC-1042` — severity, status, detected_at, affected services
- The five `INC-1042` ↔ ticket declarations
- `DEP-2041` — svc-auth 4.12.0, 2026-08-24 08:52
- `ERR_SAML_INVALID_ASSERTION` (08:55) and `401` (08:56), counts and windows
- svc-auth health: healthy 08:40 → degraded 09:10 → critical 09:25
- Hero temporal relationships and investigation evidence remain coherent
- Hero review behaviour unchanged
- The supported remediation path (rollback of `DEP-2041`) remains policy-eligible
- `INC-1043` with `TKT-4111`/`4112`/`4113`, `DEP-2044`, `ERR_SYNC_STALLED`
- Existing isolated tickets `TKT-4108`, `TKT-4109`, `TKT-4114`

---

## 12. Seed contract

Seeding is **additive and idempotent**.

**It may:** insert missing authored services, tickets, incidents and links; insert missing
operational observations; create eligible reviews through `ReviewService`.

**It must not:** delete or overwrite runtime/API-submitted tickets; delete
operator-confirmed memberships; reconstruct candidate membership from fixture declarations
in a way that erases runtime state; overwrite correlation decisions; overwrite existing
reviews or decisions; mutate `InvestigationRun`s, actions, approvals, executions or audit
history.

Candidate `ticket_count`, `first_seen` and `last_seen` come from **actual persisted
membership**, never from the fixture-declared list. This previously caused a real defect —
re-seeding a live database undercounted API-submitted and operator-attached reports — and
carries regression coverage.

Review rows are never hand-created in seed logic. A dry-run summary prints before any
production seed: what will be added, what will be preserved.

---

## 13. What this is, and is not

This expands **product context**: several unrelated failures happening near each other in
time, so correlation must choose rather than succeed by default.

- No historical eval artifact is touched. M5, M6, M8, M10, M11, M14–M18 stay exactly as
  recorded, attributable to the data that produced them.
- The single runtime pass over this world is recorded as
  `northstar-world-v2-runtime-check` and labelled an **expanded authored-world
  regression** — not a benchmark, and not evidence that evaluation became more reliable.
- "The dataset grew 6×, therefore evaluation is more reliable" is a claim this work does
  not support and will not make. A larger set authored and then measured against by the
  same author is worth less, not more, than a small one that is honestly labelled.
