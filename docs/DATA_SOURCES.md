# Data Sources, Licenses, and Attribution

IncidentIQ uses synthetic and publicly licensed data only. No real customer, employee, or
personal data is used anywhere in this project.

This file is the authoritative record of every external dataset, its license, and the
constraints we operate under. Handling rules for implementation work live in
`.claude/skills/incidentiq-builder/references/data.md`.

---

## 1. Synthetic IT Support Tickets

- **Source:** `ameau01/synthetic-it-support-tickets`
- **License:** MIT
- **Status:** Approved for use, including within the application.

### Usage in this project

- Historical incident retrieval
- Troubleshooting history
- Root-cause ground truth
- Resolution ground truth
- Retrieval evaluation
- Demo/reference data where appropriate

### Nature of the data

Explicitly synthetic. Contains no real personal or customer data.

### Obligations

The MIT license requires that the copyright notice and permission notice be preserved in
copies and substantial portions of the material. Where this data or a derivative is
redistributed, ship the upstream notice alongside it.

> **TODO before first redistribution:** copy the exact upstream copyright line and MIT
> license text from the source repository into `data/raw/LICENSE-synthetic-it-support-tickets`
> (or an equivalent committed location). Do not paraphrase it.

---

## 2. Polaris Support Tickets v2

- **Source:** `VladislavMarinovich/polaris-support-tickets-v2`
- **License:** Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)
- **License text:** https://creativecommons.org/licenses/by-sa/4.0/
- **Status:** Approved for use as an **external evaluation dataset**. Not bundled into the
  application.

### Usage in this project

- Ticket correlation evaluation
- Outage / event grouping
- Priority and routing evaluation
- Temporal incident detection

The fields `event_id`, `event_type`, `topic`, and `priority` are used strictly as **hidden
evaluation labels** where applicable. They are held in the label view and never reach
runtime features, prompts, or model inputs.

### Attribution

> "Polaris Support Tickets v2" by VladislavMarinovich, used under
> [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/).
> Any adapted material derived from it is likewise licensed under CC BY-SA 4.0, with changes
> indicated.

### Constraints we hold ourselves to

1. The raw dataset is **not committed** to this repository. `data/raw/` and
   `data/processed/` are gitignored.
2. The dataset is obtained through a reproducible download script
   (`scripts/download_polaris.py`), not a manual copy.
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
- **Location:** `data/demo/northstar_cloud/` — 3 services, 11 tickets, 2 incidents, 8
  declared incident↔ticket links.

Northstar Cloud is a fictional demo organization. Its fixtures — today services, tickets,
incidents, and the links between them; later deployments, service-health signals, runbooks,
and actions — are authored by us and checked in.

**These fixtures are not derived from Polaris or any other external dataset.** Renaming or
lightly editing external records into Northstar Cloud data is prohibited: it would be both a
licensing problem and a misrepresentation of what the demo demonstrates.

---

## Repository layout

```
data/
  README.md        # what each directory holds, and which are gitignored
  demo/
    northstar_cloud/ # Northstar Cloud fixtures — original, committed
  raw/             # downloaded datasets — gitignored
  processed/       # derived artifacts — gitignored
scripts/
  download_itsm.py     # ameau01/synthetic-it-support-tickets
  download_polaris.py  # VladislavMarinovich/polaris-support-tickets-v2
docs/
  DATA_SOURCES.md  # this file
```

## Adding a new data source

Do not introduce another dataset without first: identifying its license, confirming it
permits our intended use, recording the decision in this file, and updating
`.claude/skills/incidentiq-builder/references/data.md` if it changes how data is handled.
