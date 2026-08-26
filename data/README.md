# Data directories

Three kinds of data live here, and they never mix.

| Directory | Contents | Committed? |
|---|---|---|
| `demo/northstar_cloud/` | Northstar Cloud fixtures — original synthetic data we authored, served by the API | Yes |
| `raw/itsm/`, `raw/polaris/` | Datasets downloaded from Hugging Face | **No — gitignored** |
| `processed/itsm/`, `processed/polaris/` | Normalized JSONL derived from `raw/` | **No — gitignored** |

`raw/` and `processed/` stay out of version control. The Polaris dataset is CC BY-SA 4.0,
and committing it — raw or processed — would amount to redistributing it through this
repository. Datasets are reproduced by running the scripts, not by cloning.

## Reproducing the external data

```bash
cd apps/api
uv sync
uv run python scripts/download_itsm.py        # 745 records
uv run python scripts/preprocess_itsm.py
uv run python scripts/download_polaris.py     # 23,994 records
uv run python scripts/preprocess_polaris.py
```

Both preprocessors accept `--limit N --seed S` for a deterministic sample; the default is
the full corpus. Reruns are safe — a file already recorded at the current upstream
revision is left alone, and a file the scripts did not write is never overwritten without
`--force`. Each directory gets a `source.json` / `processed.json` recording the dataset
id, upstream revision, license, and record counts.

## What ends up where

```
raw/itsm/data/train.parquet          processed/itsm/records.jsonl
raw/polaris/polaris_tickets_v2.parquet
                                     processed/polaris/features.jsonl
                                     processed/polaris/labels.jsonl
```

**Polaris features and labels are separate files on purpose.** `labels.jsonl` holds
ground truth (`event_id`, `event_type`, `topic`, `priority`, `routing`, `sentiment`) used
only for scoring. Nothing that builds runtime features, embedding text, or prompts may
read it. See [../docs/DATA_SOURCES.md](../docs/DATA_SOURCES.md).

## Northstar independence

Northstar Cloud fixtures in `demo/` are original work, generated reproducibly and labeled
synthetic. **They are never derived from, merged with, or augmented by external dataset
records**, and the API serves only them. The external corpora are development reference
data and an evaluation benchmark — not Northstar records.
