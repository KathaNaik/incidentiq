# Data Sources, Licenses, and Attribution

IncidentIQ uses synthetic and publicly licensed data only. No real customer, employee, or
personal data is used anywhere in this project.

This file is the authoritative record of every external dataset, its license, and the
constraints we operate under. Handling rules for implementation work live in
`.claude/skills/incidentiq-builder/references/data.md`.

---

## 1. Synthetic IT Support Tickets

- **Source:** `ameau01/synthetic-it-support-tickets` (Hugging Face dataset repository)
- **License:** MIT
- **Status:** Ingested. Approved for use, including within the application.
- **Revision in use:** `e5ebd6c6bb955c136c9f45b6fe1503d8331d0a91` — 745 records, one
  parquet file (`data/train.parquet`). The exact revision is recorded in
  `data/raw/itsm/source.json` at download time.

### Commands

```bash
cd apps/api
uv run python scripts/download_itsm.py      # -> data/raw/itsm/
uv run python scripts/preprocess_itsm.py    # -> data/processed/itsm/records.jsonl
```

Add `--limit N --seed S` to the preprocess command for a deterministic sample. Neither
directory is committed.

### Usage in this project

- Historical incident retrieval
- Troubleshooting history
- Root-cause ground truth
- Resolution ground truth
- Retrieval evaluation
- Demo/reference data where appropriate

### Nature of the data

Explicitly synthetic. Contains no real personal or customer data. Note that the free text
carries **injected synthetic PII** (invented names, usernames, hostnames, IP addresses)
plus redaction ground truth — fabricated, but it means the corpus should not be pasted
into places where it could be mistaken for real user data.

### Obligations

The MIT license requires that the copyright notice and permission notice be preserved in
copies and substantial portions of the material. Where this data or a derivative is
redistributed, ship the upstream notice alongside it.

**Attribution:** Copyright (c) 2026 Alexander Meau. The upstream notice is committed
verbatim at
[`docs/licenses/ameau01-synthetic-it-support-tickets-LICENSE.txt`](licenses/ameau01-synthetic-it-support-tickets-LICENSE.txt),
copied byte-for-byte from the `LICENSE` file in the dataset repository at revision
`e5ebd6c6bb955c136c9f45b6fe1503d8331d0a91`. The download script also fetches that file
into `data/raw/itsm/LICENSE` alongside the data.

---

## 2. Polaris Support Tickets v2

- **Source:** `VladislavMarinovich/polaris-support-tickets-v2`
- **License:** Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
- **License text:** https://creativecommons.org/licenses/by-sa/4.0/
- **Status:** Ingested as an **external evaluation dataset**. Not bundled into the
  application.
- **Revision in use:** `422b34294f967c0b3c3eeb2f288de7d9db3958a8` — 23,994 records, of
  which 6,000 carry a service-event id. Recorded in `data/raw/polaris/source.json`.

### Commands

```bash
cd apps/api
uv run python scripts/download_polaris.py     # -> data/raw/polaris/
uv run python scripts/preprocess_polaris.py   # -> data/processed/polaris/{features,labels}.jsonl
```

`--limit N --seed S` takes a deterministic sample. Sampling happens on source rows before
the feature/label split, so the two artifacts can never diverge. Nothing here is committed.

### Usage in this project

- Ticket correlation evaluation
- Outage / event grouping
- Priority and routing evaluation
- Temporal incident detection

### Feature/label separation

The 15 source columns are split into two artifacts that share only `ticket_id`:

| View | Columns | File |
|---|---|---|
| **Features** — observable at intake | `ticket_id`, `created_at`, `channel`, `plan`, `user_role`, `reported_category`, `subject`, `body` | `features.jsonl` |
| **Labels** — ground truth, scoring only | `ticket_id`, `topic`, `type`, `priority`, `routing`, `sentiment`, `event_id`, `event_type` | `labels.jsonl` |

`reported_category` is a feature because the reporter picks it at submission and it is
frequently wrong; `topic` is the label because it is the correct answer. `event_id` is the
correlation answer key — tickets sharing one are reports of the same underlying event.

The separation is structural, not advisory: the feature model forbids unknown fields, so a
feature record cannot be constructed from a raw row at all, and the feature module does not
import the label module. Tests derive the label set from the label model and assert none of
it appears in serialized features, so a label added upstream is covered automatically.

### Attribution

> "Polaris Support Tickets v2" by VladislavMarinovich, used under
> [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Any adapted material derived from it is likewise licensed under CC BY-SA 4.0, with changes
> indicated.

### Constraints we hold ourselves to

1. The raw dataset is **not committed** to this repository. `data/raw/` and
   `data/processed/` are gitignored.
2. The dataset is obtained through a reproducible download script
   (`apps/api/scripts/download_polaris.py`), not a manual copy.
3. Polaris data is **never presented as IncidentIQ's own synthetic data**, and its records
   are never relabeled as Northstar Cloud data.
4. We avoid redistributing modified copies of the dataset unless there is a concrete need.
5. **If distribution of adapted Polaris data is ever proposed, that decision gets flagged
   and handled explicitly first** — CC BY-SA 4.0 ShareAlike obligations attach to adapted
   material and are not something to assume our way through.

Internal use for evaluation does not trigger the redistribution obligations. Publishing
adapted copies does. That distinction is why the dataset stays out of the repository.

---

## 3. Northstar Cloud demo fixtures

- **Source:** Original work, authored for this project.
- **License:** Same as this repository.
- **Status:** In use. Synthetic, and labeled as such by the API (`GET /dataset`) and in a
  banner on every page of the web app.
- **Location:** `data/demo/northstar_cloud/` — 8 services, 68 tickets, 10 incidents, 41
  declared incident↔ticket links, plus 10 deployments, 35 health observations and 12 error
  records. The design that produced it is frozen in
  [NORTHSTAR_WORLD_V2.md](NORTHSTAR_WORLD_V2.md), written before any record was authored
  so the intended grouping could not drift toward whatever the algorithm happened to
  score well.
- **Independence:** the external corpora are never merged into these files. Northstar is
  what the product demonstrates; ITSM and Polaris are reference and benchmark data that
  live in separate, uncommitted directories and are not served by the API.

Northstar Cloud is a fictional demo organization. Its fixtures — services, tickets,
incidents and the links between them, deployments, service-health sequences, error
observations and runbooks — are authored by us and checked in.

The world spans three operational waves: the original authentication incident, a busy
morning of five overlapping incidents across five services, and an afternoon of three more.
Causal shapes vary deliberately — four incidents involve no deployment at all, one has a
deployment that arrives *after* symptoms began, and two are clean deployment attributions.
It also contains 14 ordinary support reports that belong to no incident and 10 boundary
cases whose intended grouping lives only in the design document.

Growing this world expanded **product context**, not evaluation authority. No historical
eval artifact changed, and the single runtime pass over the expanded world is recorded
separately as an *expanded authored-world regression* rather than as a benchmark.

**These fixtures are not derived from Polaris or any other external dataset.** Renaming or
lightly editing external records into Northstar Cloud data is prohibited: it would be both a
licensing problem and a misrepresentation of what the demo demonstrates.

---

## Repository layout

```
data/
  README.md              # what each directory holds, and which are gitignored
  demo/
    northstar_cloud/     # Northstar Cloud fixtures — original, committed
  raw/                   # downloaded datasets — gitignored
    itsm/  polaris/
  processed/             # derived artifacts — gitignored
    itsm/  polaris/
apps/api/
  ingestion/             # adapters, validation, feature/label split
  scripts/
    download_itsm.py       download_polaris.py
    preprocess_itsm.py     preprocess_polaris.py
docs/
  DATA_SOURCES.md        # this file
  licenses/              # verbatim upstream license notices
```

The scripts live inside `apps/api` because that is the Python project; running them from
the repository root would need `PYTHONPATH` juggling to import the ingestion package.

## Derived artifacts

Semantic correlation caches ticket embeddings under `data/processed/embeddings/`. Those
vectors are derived from ticket text — including the CC BY-SA corpus — so the directory
is gitignored along with the rest of `processed/`. Vectors are keyed by provider and
model identity (`fastembed:BAAI/bge-small-en-v1.5`), so a cache written by one model can
never be read by another.

## Adding a new data source

Do not introduce another dataset without first: identifying its license, confirming it
permits our intended use, recording the decision in this file, and updating
`.claude/skills/incidentiq-builder/references/data.md` if it changes how data is handled.
