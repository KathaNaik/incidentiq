# IncidentIQ — Data Reference

Only synthetic, public, or legally permissible data. No real customer or employee data.

Both external datasets below have been license-reviewed and **approved for use** under the
constraints in this document. Do not introduce a third dataset without a fresh license
review recorded here and in `docs/DATA_SOURCES.md`.

## Primary datasets

### `ameau01/synthetic-it-support-tickets` — MIT

Approved for use, including bundling with the application.

Used primarily for:
- historical incidents
- troubleshooting history
- root-cause ground truth
- resolution ground truth
- retrieval evaluation
- demo/reference data where appropriate

Obligations: preserve the upstream copyright notice and MIT license text wherever the data
or a derivative of it is redistributed. Record the attribution in `docs/DATA_SOURCES.md`.

Content is explicitly synthetic and contains no real personal or customer data.

### `VladislavMarinovich/polaris-support-tickets-v2` — CC BY-SA 4.0

Approved for use, but **treat it as an external evaluation dataset, not application
content.** It supports:
- ticket correlation evaluation
- outage / event grouping
- priority and routing evaluation
- temporal incident detection

Hard rules for this repository:

- **Do not commit the raw Polaris dataset.** Raw and processed dataset directories are
  gitignored.
- Obtain it through a reproducible download/ingestion script (`scripts/download_polaris.py`),
  never a manual copy checked into the tree.
- Attribution and the CC BY-SA 4.0 license notice live in `docs/DATA_SOURCES.md`.
- Never present Polaris data as IncidentIQ's own synthetic data, and never relabel Polaris
  records as Northstar Cloud.
- Keep its ground-truth fields isolated from runtime and model inputs. `event_id`,
  `event_type`, `topic`, and `priority` are **hidden evaluation labels** where used as such.
- Avoid redistributing modified copies unless there is a concrete need.
- If distribution of adapted Polaris data is ever proposed, **stop and flag the decision
  before doing it** — CC BY-SA imposes ShareAlike obligations on adapted material that must
  be handled explicitly, not assumed.

Internal use for evaluation does not trigger the redistribution obligations; publishing
adapted copies does. That distinction is the reason for the "don't commit it" rule.

## Repository layout for data

```
data/
  README.md        # what each directory holds, and which are gitignored
  demo/            # our own Northstar Cloud fixtures — committed
  raw/             # downloaded datasets — gitignored
  processed/       # derived artifacts — gitignored
scripts/
  download_itsm.py     # ameau01/synthetic-it-support-tickets
  download_polaris.py  # VladislavMarinovich/polaris-support-tickets-v2
docs/
  DATA_SOURCES.md  # sources, licenses, attribution, usage constraints
```

`data/raw/` and `data/processed/` must be gitignored before any download script is run.
Ingestion must be reproducible from a clean checkout: run the script, get the dataset.

## Leakage rule (hard constraint)

Ground-truth fields — event IDs, cluster/outage labels, resolution labels, root-cause
labels, and the Polaris `event_id` / `event_type` / `topic` / `priority` fields when used as
labels — **must never reach model inputs or runtime features.**

Practical enforcement:
- Split ingestion into a *runtime feature view* and a *label view*; runtime code may only
  read the feature view.
- Strip label columns at the ingestion boundary, not at the prompt.
- Add a test that fails if a label field appears in any runtime feature payload or prompt.

## Demo organization: Northstar Cloud

A very small fictional organization with controlled fixtures for the polished demo. It may
contain synthetic services, tickets, historical incidents, deployments, service-health
signals, runbooks, and actions.

Rules:
- **Northstar Cloud fixtures must be original work that we generate.** Renaming or lightly
  editing Polaris (or any external) records into Northstar Cloud data is not acceptable —
  it is both a licensing problem and a misrepresentation of what the demo shows.
- Keep fixtures small and hand-checked — they exist to make the demo crisp, not to inflate
  data volume.
- Mark every demo fixture clearly as synthetic (a field on the record and a visible label
  in the UI, not just a comment in a seed file).
- Fixtures may shape a scenario, but must never bypass the real pipeline. If the demo path
  short-circuits triage, correlation, or investigation, that is a hard-coded demo output
  disguised as model reasoning — reject it.
- Keep fixture generation reproducible (seeded, checked in, re-runnable).
