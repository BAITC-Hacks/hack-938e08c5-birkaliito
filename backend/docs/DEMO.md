# Reproducible demo

From backend, run `make run-mock` (Windows: `./tools/task.ps1 run-mock`). Open `http://127.0.0.1:8080/docs`. In another terminal run `make smoke` or `go run ./cmd/smoke`.

Smoke does GET meta → POST fixture with Idempotency-Key → repeat same key (same ID) → changed body (409) → SSE until stream_end → GET completed job → schema-validated 96-point result → 97-row CSV including header. Fixtures and tests require no Python, LLM key, GFS or trained model.

## Recovery and failures

Restart with server-side `MOCK_SCENARIO=degraded`. The event log shows a simulated source failure and an allowed fixture recovery. The job completes with quality_status=degraded. This is a simulation of recovery, not a LangGraph run.

Other server scenarios:

| Scenario | Expected result |
|---|---|
| success | completed/passed |
| degraded | completed/degraded, warning and recovery event |
| failure | failed/MOCK_TOOL_FAILED; no result |
| slow | long worker delay; demonstrate live events and cancellation |
| llm_unavailable | completed numerical result, unavailable explanation |
| weather_future | policy_rejected then failed; publication prohibited |

For a failure server run `go run ./cmd/smoke -expect failed`. For cancellation use POST `/api/jobs/{id}/cancel`, then observe the terminal job. Merely closing the event stream leaves the job running.

PowerShell example:

```powershell
$env:MOCK_SCENARIO='degraded'
.\tools\task.ps1 run-mock
# Second terminal:
go run ./cmd/smoke
```

## Replay

POST `/api/replays` with an Idempotency-Key:

```json
{"origins":["2026-01-31T18:00:00Z","2026-02-01T18:00:00Z"],"horizon_hours":48,"turbine_ids":[1,2],"model_version":"fixture-not-trained","data_mode":"fixture"}
```

Read `/api/replays/{id}` and `/runs`. When completed, `/export` contains 192 data rows, including overlapping target times as distinct releases. Cancel a slow replay; its terminal `/export` rejects 409 unless `allow_partial=true`. Partial export exposes counts and preserves completed children.

Historical origins are simulated issue times. Event recorded_at and job created_at are current system execution times. February has 672 target hours per turbine, but overlapping releases intentionally contain more rows. Replay never asserts access to real February observations.

## Offline handoff

`go run ./cmd/fixtures` rebuilds the checked-in examples from the same application handlers, validates every example against OpenAPI and writes manifest.json. The examples include loading/failure/degraded/cancelled/empty/unavailable states. `/docs` needs only the running Go binary; dependencies must be downloaded once before offline compilation.
