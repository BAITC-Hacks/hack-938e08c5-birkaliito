# Frontend handoff

Start with [canonical OpenAPI](../api/openapi.yaml), [generated types](../contracts/typescript/api-types.ts), [typed client](../contracts/typescript/client.ts) and [complete fixtures](../testdata/fixtures/manifest.json). The backend API is implemented; React/ML code was not edited. `/docs` is a local offline viewer of the same contract.

## Minimal flow

```ts
import { WindClient } from '../contracts/typescript/client';
const api = new WindClient(''); // same-origin dev proxy to Go
const meta = await api.getMeta();
const models = await api.listModels();
const operationKey = crypto.randomUUID(); // reuse only for retries of this action
const job = await api.createForecast({
  forecast_origin: '2026-01-31T18:00:00Z',
  model_version: 'fixture-not-trained', data_mode: 'fixture',
}, operationKey);
const subscription = api.subscribeJobEvents(job.job_id, {
  onEvent: event => console.log(event.node, event.message),
  onEnd: async final => {
    if (final.status === 'completed') console.log(await api.getResult(job.job_id));
    else console.log(await api.getJob(job.job_id));
  },
  onError: error => console.error(error),
});
// On unmount: subscription.close(); abort request controllers.
// User cancellation is a separate await api.cancelJob(job.job_id).
```

Defaults when omitted: horizon_hours=48, turbine_ids=[1,2], mode=replay, **data_mode=real**. Mock callers must explicitly send fixture. Required forecast_origin/model_version cannot be null or empty. Unknown fields are rejected. Only 24/48 hours and unique turbine IDs 1/2 are valid. All timestamps need an explicit offset; origins align to UTC whole hours. Output timestamps are UTC; UI may display Asia/Almaty with an explicit label.

`job_id == run_id` for forecast and `job_id == replay_id` for replay. 202 is acceptance, not a finished chart. Job states are queued/running/completed/failed/cancelled. `cancel_requested` is a separate detail flag. A degraded forecast is completed with `quality_status=degraded`, not a new job status. Numeric results survive LLM unavailability.

## Available client methods

getMeta, listTurbines, listModels, createForecast, listForecasts, getForecastDetails, getJob, getResult, getEvents, subscribeJobEvents, cancelJob, createReplay, getReplayDetails, listReplayRuns, getWeather, getExplanation, listEvaluations, getEvaluation, getDataQuality, exportForecast and exportReplay. All HTTP methods support AbortSignal. Non-2xx raises ApiException containing HTTP status and `{code,message,request_id}`. No server keys are accepted or needed by the browser.

New lists have `{items,next_cursor}`. `getEvents` and `listReplayRuns` retain arrays. Forecast filters: forecast_origin_from/to ([from,to)), turbine_id, status, data_mode, limit (25 default, max 100), cursor. Cursors are opaque and bound to filters/page size; reset cursor when filters change. History rows contain requests/jobs, not 96-point results. Overlapping valid_time across distinct releases is expected.

## Streaming

`GET /api/jobs/{id}/stream?after=N` returns `event: agent_event`, `id: event_id`, AgentEvent JSON. Native reconnect uses Last-Event-ID; header takes priority, but both sources must be valid. Heartbeats are comments and have no IDs. Deduplicate `(job_id,event_id)`. The typed client ignores already seen IDs.

After all final events the server sends `stream_end` with `{job_id,status}` and no ID. Close EventSource. The client does this and falls back to bounded event/job polling when SSE is unavailable. `stream_error` is a safe control error; it never changes the job's state. Polling terminates on expired/malformed cursor or unavailable capability; show the problem and explicitly restart viewing from retained state. Disconnect/unmount never cancels the job.

Use a same-origin React development proxy for `/api`, `/healthz`, `/readyz`, `/docs` and `/openapi.yaml` to `http://127.0.0.1:8080`. Native EventSource cannot set arbitrary Authorization headers. Python/LLM tokens must never appear in VITE_* variables.

## Screens and honest labels

| UI state / screen | Ready fixture examples / behavior |
|---|---|
| Initial / empty history | history-empty.fixture.json |
| Submitting / queued | success-queued.fixture.json; POST 202 |
| Running | running.fixture.json; show stage, no invented percent |
| Completed | success-result.fixture.json (96 points), 24-one/24-two/48-one-result fixtures |
| Degraded completion | degraded-result.fixture.json and degraded-events.fixture.json |
| Failed / policy rejected | failure-job / weather_future-job fixtures; result remains 409 |
| Cancellation | slow-job.fixture.json; completed results cannot be cancelled |
| Dependency unavailable | dependency-unavailable.fixture.json; /readyz 503 |
| LLM unavailable | llm_unavailable-result.fixture.json; retain chart |
| Weather tab | success-weather.fixture.json; forecast GFS features, not SCADA observations |
| Explanation / SHAP | success-explanation.fixture.json; shap_status=unavailable, no invented ranking |
| Replay | replay-details.fixture.json and replay-runs.fixture.json; real child counters |
| Evaluation | evaluations.fixture.json; visibly synthetic metrics |
| No quality report | metrics-unavailable.fixture.json; null metrics, no zero substitution |
| Data audit | data-quality.fixture.json; synthetic example, timezone unconfirmed |

Keep **«Синтетические данные — режим разработки»** visible whenever data_mode=fixture. Check `/api/meta` and `/api/models` before enabling actions; false capability disables action with an explanation. Mock advertises simulated=true. SHAP is unavailable until a genuine artifact is supplied.

Power unit is normalized_power with unconfirmed normalization. No MW/MWh, fabricated rated capacity, station energy or summed turbine quantile interval. q10–q90 is an uncertainty interval, not a guarantee. There are no February observed targets available from this backend, hence no February fact line or measured February accuracy. Missing values are null/unavailable, not zero.

Forecast plotting uses turbine_id, valid_time, power_mean, q10/q50/q90. valid_time begins the interval; interval_end is its end. Lead 1 begins one hour after origin. Mean is not necessarily median. Use labels/styles beyond color to distinguish turbines and releases.

## Errors, cancellation, export

400 malformed JSON/cursor; 413 body limit; 415 content type; 422 semantic input/model/mode; 403 fixture configuration prohibition; 404 missing resource; 409 state/idempotency conflict; 410 expired events; 429 stream capacity; 501 unsupported capability; 502 invalid upstream; 503 unavailable dependency/queue; 504 deadline. Error codes distinguish RESULT_NOT_READY from IDEMPOTENCY_CONFLICT. New user action gets a new key; retry preserves it.

Cancellation is 202 while running; 200 if already/immediately cancelled. Keep polling until terminal. Completed/failed cancellation returns 409 JOB_NOT_CANCELLABLE. Replay counters total/queued/running/completed/failed/cancelled are authoritative; progress may use terminal children/total with failures shown separately.

CSV columns: run_id,forecast_origin,turbine_id,valid_time,interval_end,lead_hours,power_mean,q10,q50,q90,data_mode. Stable turbine/lead order, UTC and decimal dots. Export helpers return Blob; replay helper also exposes status/counters. Failed/cancelled terminal replay needs explicit `allow_partial=true`; headers label it partial. Never label a partial download as the entire February batch.

Render explanation as text or sanitized markup, never raw HTML. Treat provenance references as information, not automatic download instructions.
