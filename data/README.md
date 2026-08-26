# Data directories

`demo/` holds the Northstar Cloud fixtures the API currently serves. External dataset
ingestion is not implemented — `raw/` and `processed/` do not exist yet.

| Directory | Contents | Committed? |
|---|---|---|
| `demo/northstar_cloud/` | Northstar Cloud fixtures — original synthetic data we authored | Yes |
| `raw/` | Datasets fetched by the download scripts | **No — gitignored** |
| `processed/` | Artifacts derived from `raw/` | **No — gitignored** |

`raw/` and `processed/` stay out of version control. The Polaris dataset is CC BY-SA 4.0,
and committing it here would amount to redistributing it through this repository. Datasets
are reproduced by running the download scripts, not by cloning.

Northstar Cloud fixtures in `demo/` must be original work, generated reproducibly and
labeled synthetic. They are never derived from external dataset records.

Licenses, attribution, and full constraints: [../docs/DATA_SOURCES.md](../docs/DATA_SOURCES.md).
