# IncidentIQ

AI-assisted incident investigation for technical operations teams.

IncidentIQ turns fragmented technical support tickets plus operational context into a
correlated incident, an evidence-backed root-cause hypothesis, and a recommended
remediation that a human approves before anything runs.

**Status:** early. The domain model (services, tickets, incidents, and the links between
incidents and tickets) is defined and served over a read-only API, backed by synthetic
Northstar Cloud fixtures. None of the AI capabilities — triage, correlation,
investigation, remediation, evaluation — are implemented yet, and no external dataset has
been ingested.

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
| `NEXT_PUBLIC_API_BASE_URL` | web | `http://localhost:8001` | Backend base URL used by the browser |

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

## Data and licensing

**Northstar Cloud is a fictional organisation.** Every record the API serves today is
fabricated and was authored specifically for IncidentIQ — see
[data/demo/northstar_cloud/README.md](data/demo/northstar_cloud/README.md). No external
dataset has been ingested yet.

External datasets are license-reviewed before use, and the CC BY-SA Polaris dataset is
never committed to this repository. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
