# Wind Forecast Go API

Go 1.25.6 / Gin 1.11.0 backend for the wind forecast contract. `mock` runs independently; `http` talks to the proposed Python protocol. The Python model, GFS loader, LangGraph worker and React application are outside this backend.

## Start

From `backend/`:

```sh
go mod download
make run-mock
# In a second terminal:
make smoke
```

Windows PowerShell without GNU Make:

```powershell
.\tools\task.ps1 run-mock
# In a second terminal:
.\tools\task.ps1 smoke
```

Equivalent commands are `go run ./cmd/api` (defaults to mock) and `go run ./cmd/smoke`. API: `http://127.0.0.1:8080`; local, offline documentation viewer: `/docs`; canonical contract: `/openapi.yaml`. The viewer reads the same embedded YAML as validation and needs no CDN. `.env.example` documents configuration; the binary reads process environment, it does not automatically load `.env`.

```sh
curl -H 'Content-Type: application/json' -H 'Idempotency-Key: demo-001' \
  -d '{"forecast_origin":"2026-01-31T18:00:00Z","model_version":"fixture-not-trained","data_mode":"fixture"}' \
  http://127.0.0.1:8080/api/forecast-runs
```

The 202 response is a job, not a finished forecast. Use its `job_id` for `/api/jobs/{id}`, `/api/jobs/{id}/stream`, and `/api/forecast-runs/{id}/result`. Forecast `job_id == run_id`; replay `job_id == replay_id`.

## Implemented surface

| Routes | Behavior |
|---|---|
| `GET /healthz`, `/readyz`, `/api/meta` | Process health, dependency readiness, capabilities |
| `GET /api/turbines`, `/api/models` | Configured turbine metadata, model catalog |
| `POST /api/forecast-runs`, `GET /api/forecast-runs` | Async creation, idempotency, filtered cursor history |
| `GET /api/forecast-runs/{id}` | Original request, job metadata, availability, cancellation |
| `GET /api/forecast-runs/{id}/result`, `/export` | Validated immutable result and CSV |
| `GET /api/forecast-runs/{id}/weather`, `/explanation` | Separate weather artifact, text and SHAP availability |
| `GET /api/jobs/{id}`, `/events`, `/stream` | State, retained event log, SSE with resume and terminal control event |
| `POST /api/jobs/{id}/cancel` | Cancellation through job owner |
| `POST /api/replays`, `GET /api/replays/{id}`, `/runs`, `/export` | Historical batch, actual child counters, explicit partial CSV |
| `GET /api/evaluations`, `/api/evaluations/{id}`, `/api/data-quality` | Typed read models; fixture/unavailable examples |

See [OpenAPI](api/openapi.yaml) for defaults, nullability, all status codes and parameters. Existing response objects and event/child arrays have no success/data envelope. New lists have `items` and `next_cursor`.

## Architecture and ownership

`HTTP → incoming usecase interface → application service → consumer-owned ports → mock / Python adapters`. All wiring is in `internal/app.New`; one immutable configuration, logger and HTTP client/transport per App. Domain has no JSON tags or infrastructure imports. Generated DTOs and upstream DTOs map explicitly to domain entities.

In mock, a bounded in-memory adapter owns the queue, job state, results and events. Atomic check/create/enqueue guarantees a repeated key cannot create two jobs. A fixed worker pool performs actual asynchronous simulation. Nothing starts on a GET. Retained completed results are immutable; callers receive copies.

Mock storage is **volatile**: restart loses jobs and idempotency entries. No automatic job eviction occurs. At the configured retention or queue limit, creation returns 503 `QUEUE_FULL`; retry of an existing key still works. Replay registration reserves all child queue slots atomically, so large batches require increasing `MOCK_QUEUE_CAPACITY` and `MOCK_MAX_JOBS` (366 origins need at least 366 queue slots and 367 job slots). Events use a bounded ring; expired cursors return 410. This is not production durable execution.

In HTTP mode Python exclusively owns real state, durable acceptance, results, manifests and checkpoints. Go has no real job database/queue, never invents IDs on dependency failure and never substitutes fixture data. The adapter validates schema, identity, timestamps, complete turbine/lead coverage and quantiles before publication. `/events` polling builds downstream SSE from the upstream log.

## Real Python integration

```powershell
$env:AGENT_MODE='http'
$env:ALLOW_FIXTURES='false'
$env:PYTHON_BASE_URL='http://localhost:8000'
$env:PYTHON_INTERNAL_TOKEN='your-server-only-token'
go run ./cmd/api
```

The proposed endpoints start with `/internal/v1`, including `/internal/v1/meta` and `/internal/v1/readyz`. Details: [PYTHON_INTEGRATION.md](docs/PYTHON_INTEGRATION.md). Optional unsupported capabilities return 501; dependency downtime returns 503/504. No actual Python/CatBoost service was supplied, so real model integration remains unverified. Adapter tests use `httptest.Server` and no internet.

## Time, data and units

Inputs require explicit UTC offsets and whole-hour origins after UTC normalization. Outputs use UTC. `valid_time = origin + lead_hours`, leads are 1..H; `interval_end = valid_time + 1h`, so the last interval ends H+1 hours after origin. 48 hours × 2 turbines produces exactly 96 points. Overlapping origins remain separate releases in history and exports.

`normalized_power` has unconfirmed normalization and no imposed [0,1] range. Rated power and hub height stay null until verified. No conversion to MW/MWh, no station energy calculation, no addition of turbine quantiles. `Asia/Almaty` is display configuration only; raw CSV timezone is unconfirmed. Missing observations are not zero.

Real results must satisfy `initialization_time <= effective_available_at <= forecast_origin` and `training_data_available_through <= forecast_origin`. Retrieval now may be later than historical origin. Go checks declared metadata; Python must establish source authenticity, checksums, data availability policy and absence of February observation leakage. February measured power/wind/temperature must not become forecast inputs in the main replay.

## Checks and generated contracts

```sh
gofmt -w .
go mod tidy
go build ./...
go vet ./...
go test ./...
go test -race ./...
make smoke
cd contracts/typescript
npm ci
npm run typecheck
```

`go run ./cmd/fixtures` regenerates complete synthetic response snapshots by executing the real HTTP application. `testdata/fixtures/manifest.json` associates every snapshot with its schema. Tests validate fixture payloads and handler responses with JSON Schema 2020-12, including date-time formats, using the canonical OpenAPI components; this is more than YAML parsing.

`python tools/generate_contract.py` regenerates the OpenAPI, boundary Go types/mappings and TypeScript types from the checked-in contract definition. Run `gofmt -w .` afterwards. No ML or frontend code is generated. Go cross-field invariants supplement schema validation. Contract clarifications are tracked in [CONTRACT_CHANGELOG.md](docs/CONTRACT_CHANGELOG.md).

## Docker

```sh
docker compose up --build
docker compose -f compose.yaml -f compose.http.yaml up --build
```

Default compose starts only the Go mock and binds the host port to localhost. The optional overlay points to a separately running Python server. Runtime is a non-root static binary in scratch; timezone data and contract/docs are embedded. Internal secrets stay server-side.

## Handoff and demo

- [Frontend handoff](docs/FRONTEND_HANDOFF.md), [TypeScript types](contracts/typescript/api-types.ts), [typed client](contracts/typescript/client.ts)
- [Architecture](docs/ARCHITECTURE.md), [Python protocol](docs/PYTHON_INTEGRATION.md)
- [Demo scenarios](docs/DEMO.md), [assumptions](docs/ASSUMPTIONS.md), [verification record](docs/VERIFICATION.md)
- [Original requirements](docs/GO_BACKEND_MASTER_PROMPT.md), [fixture responses](testdata/fixtures/manifest.json)

Every synthetic result is visibly `data_mode=fixture`, `model_version=fixture-not-trained`; every synthetic agent message starts with `MOCK:`. Quality metrics are UI fixtures, not measured accuracy. SHAP is explicitly unavailable because no verified SHAP artifact exists.
