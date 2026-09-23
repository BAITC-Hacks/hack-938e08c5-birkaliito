# Proposed Python integration protocol

This document is a handoff, not a claim that the Python service already implements these endpoints. Go's `AGENT_MODE=http` adapter uses one shared configured client and never owns real job state.

The Python-side helper has been removed because no ML service is present yet. The actual Python service must implement equivalent request defaults, UTC normalization and cross-field validation at its boundary using the canonical OpenAPI.

## Routes and transport

The suffix of each business route moves from public `/api` to private `/internal/v1`:

| Internal route | Required behavior |
|---|---|
| `GET /internal/v1/readyz` | 200 `{status:"ok"}` or 503 |
| `GET /internal/v1/meta` | Public Meta schema with agent_mode=http, simulated=false, supported capabilities |
| `GET /internal/v1/models` | ModelList; real models, actual training cutoff and quantile support |
| `POST /internal/v1/forecast-runs` | Atomic durable idempotent acceptance, 202 JobRecord |
| `GET /internal/v1/forecast-runs` | Same list filters/cursor as public API |
| `GET /internal/v1/forecast-runs/{id}` | ForecastRunDetails, including original canonical request |
| `GET /internal/v1/forecast-runs/{id}/result` | Complete immutable ForecastResult or 409 RESULT_NOT_READY |
| `GET /internal/v1/jobs/{id}` | Authoritative JobRecord |
| `GET /internal/v1/jobs/{id}/events?after=N&limit=L` | Ordered retained AgentEvent array; exclusive cursor |
| `POST /internal/v1/jobs/{id}/cancel` | 202 request accepted / 200 cancelled / 409 cannot cancel |
| `POST /internal/v1/replays` | Atomic durable acceptance, 202 replay JobRecord |
| `GET /internal/v1/replays/{id}` | Authoritative consistent child counters and metadata |
| `GET /internal/v1/replays/{id}/runs` | Child JobRecord array |
| `GET /internal/v1/forecast-runs/{id}/weather` | Separate WeatherDetails artifact |
| `GET /internal/v1/forecast-runs/{id}/explanation` | ExplanationDetails with truthful SHAP availability |
| `GET /internal/v1/evaluations[/{id}]` | EvaluationList / EvaluationReport |
| `GET /internal/v1/data-quality` | Verified ready audit artifact |

Go serves CSV from verified result objects and SSE by polling the Python event log, so upstream CSV/SSE routes are not required. No arbitrary artifact URL/path is accepted from the browser. Go owns the configured turbine catalog and process liveness.

Every response is JSON with `Content-Type: application/json`, explicit nulls and empty arrays, matching [canonical OpenAPI components](../api/openapi.yaml). Unknown fields, wrong enums, missing required values, invalid timestamps, excessive response size, unexpected status and inconsistent IDs produce 502. Independent upstream DTOs/mapping are in `internal/adapters/agenthttp`.

Go sends only `Authorization: Bearer <PYTHON_INTERNAL_TOKEN>`, validated/generated X-Request-ID, Content-Type/Accept, and Idempotency-Key where applicable. Redirect following is disabled, including cross-origin redirects. URLs originate exclusively from trusted configuration. Body size, connection limits, dial/response/header timeout and overall deadline are bounded. Raw provider bodies, tokens and internal paths are not sent to the browser.

## State, acceptance and durability

Python must guarantee `forecast job_id == run_id` and `replay job_id == replay_id`. If this differs from the actual worker, agree a contract extension rather than silently remapping identities in Go.

Normalize defaulted requests and UTC timestamps, sort turbines and replay origins for fingerprinting, and namespace idempotency by endpoint. Equal key+request returns the same job and current state; different content returns 409 IDEMPOTENCY_CONFLICT. Preserve normalized original replay order in details. Response 202 follows durable acceptance, not a speculative Go ID. A timeout may occur after acceptance; retry using the original key is mandatory for recovery.

Keep a persistent job registry, durable work queue, monotonically numbered retained event log, cancellation flags, immutable validated result/artifact manifests and worker checkpoints. Persist result and completed transition atomically; no result is published before invariant validation. Resume work safely after worker/process restart. This repository does not implement that Python persistence.

Failed child jobs prevent a completed replay. Terminal parent metadata and children must be a consistent immutable snapshot. Preserve completed child results when another child fails or replay cancellation is accepted. Empty/missing metrics are unavailable/null, never zero accuracy.

## Historical policy

Lead hours are 1..H, valid_time is interval start, interval_end is one hour later. Normalize timestamps to UTC **before** checking whole-hour origins. Every expected turbine/lead pair appears exactly once. q10 and q90 must be finite and ordered; q50 is a required nullable field and must be finite and ordered when available. Go never fabricates missing quantiles or clips model values.

Check `initialization_time <= effective_available_at <= forecast_origin` and `training_data_available_through <= forecast_origin`. `retrieved_at` is actual retrieval time and may be later. Conservative availability requires a policy ID. Real mode forbids fixture sources/versions. Future weather must be original archived forecasts actually available at the simulated issue time, not reanalysis or later observations. Main replay uses no newly arriving February SCADA targets, wind or temperature.

## Capabilities and failures

Capabilities are fetched from upstream; Go does not assume new read models are implemented. Report false for unsupported optional features; callers get 501 FEATURE_NOT_SUPPORTED. Temporary dependency failure is 503, timeout 504, malformed response 502. Upstream 404/409/422 retain their public meaning, with safe messages; a Python 5xx never causes Go to persist a failed job. No mock fallback exists.

Required for forecasting: readiness/meta/models, create/job/details/result and events. Replay/cancel/read model routes may be disabled through capabilities until implemented. Explanation should return an unavailable artifact or explicit 501. Go termination/disconnected SSE never cancels Python jobs.

The Go HTTP adapter has not been exercised against a supplied Python service. Before real deployment, verify status mapping, retries, redirects, deadlines, schema violations and historical availability with the actual ML implementation. The former local adapter tests were removed during the requested cleanup.
