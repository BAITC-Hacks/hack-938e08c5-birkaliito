# Contract changelog

## 1.2.0 — ML bridge compatibility

`ForecastPoint.q50` remains a required JSON field but may be `null` when a model does not produce a calibrated median. The merged XGBoost model publishes a point prediction (`power_mean`) and a residual-calibrated 10–90% band (`q10`, `q90`); treating its point prediction as `q50` would mislabel a mean as a median. CSV leaves the q50 cell empty in this case. Frontends should draw the mean line and available interval, and only show a median line when q50 is numeric. Go DTOs and TypeScript types are regenerated from the updated OpenAPI. The public routes and other fields are unchanged.

## 1.1.0 — backend implementation and agreed extensions

Baseline: `Downloads/wind_backend_handoff/baseline_contracts/`, OpenAPI 3.1.0 contract 1.0.0 and its Go/TypeScript/Pydantic transport types. Existing `/api/...` paths and successful object/array shapes are preserved. No `/api/v1` migration and no response envelope.

Clarifications explicitly introduced by the master requirements:

- Origin whole-hour alignment is checked **after UTC normalization**. `23:30+05:30` is valid for `18:00Z`; `23:00+05:30` is not a UTC whole hour. Output dates are UTC. Python must adopt this rule rather than the baseline check of local `minute` before normalization.
- Forecast `job_id == run_id`; replay `job_id == replay_id`. These are requirements on the proposed internal Python protocol.
- Creation keys are required, 1..128 visible ASCII characters. Canonical requests include defaults, sorted turbines, UTC timestamps, model, mode/data_mode and endpoint. Replay origins are sorted only for fingerprinting; details preserve normalized user order.
- Public resource IDs are opaque 1..128 ASCII letters/digits/underscore/hyphen, starting with a letter/digit. They are never paths.
- Both create endpoints return 202 after owner acceptance. Mock acceptance is in-memory, not durable; the baseline response description promising durable persistence was corrected.
- Job nullable errors, weather availability policy ID, event evidence arrays and API error request ID are always present in responses. Errors use `{code,message,request_id}`. Request `null` is never treated as omission/default.
- Event IDs are bounded by JavaScript's safe integer maximum. Stream event name is `agent_event`; `stream_end` and `stream_error` control events have no IDs. Both cursors are validated; Last-Event-ID wins. Event limit defaults to 100/max 1000. Expired history gives 410.
- New read routes, cancellation, replay details/export, health/meta and documentation routes are in the canonical schema. New lists use `{items,next_cursor}`; turbine/model lists currently fit one page and have `next_cursor=null`. Existing events and replay children remain arrays.
- Forecast history default limit 25/max 100; origin range [from,to); stable created_at DESC/job_id DESC order. Cursors bind to filters and page size. Invalid cursors are 400; invalid semantic filters/limits are 422.
- Evaluation metric JSON keys are `mae`, `rmse`, `bias`, `coverage_q10_q90`, `mean_interval_width`. Each is nullable; unavailable metrics and n_observations are null. This fixes casing/nullability that was not specified by the baseline.
- Data-quality row/hour counts and ranges are nullable when unavailable. `generated_at`/`source_reference` are nullable. No unknown count is represented as zero.
- Replay export only accepts terminal batches. Unsuccessful batches require `allow_partial=true`. Response headers `X-Replay-Export-Status` and Total/Completed/Failed/Cancelled are described and exposed through CORS.
- Cancellation returns 202 while pending, or 200 for already/immediately cancelled. Completed/failed cancellation is 409. No extra public cancelling/degraded job status.
- `capabilities.simulated` is always a boolean; true in mock, false in HTTP. SHAP can be unavailable without making the forecast unavailable.

The future Python implementation must use the clarified UTC alignment/default rules. `python tools/generate_contract.py --check` detects drift in checked-in OpenAPI, Go mappings and TypeScript types.

Canonical `api/openapi.yaml` uses JSON syntax, a valid YAML 1.2 representation. This makes the embedded offline viewer dependency-free. It remains the single OpenAPI schema consumed by validators and documentation. `tools/generate_contract.py` regenerates it together with boundary DTOs and TypeScript. No Swagger 2.0 document is maintained.

No changes to baseline lead-time convention, quantile requiredness, target units or field names such as power_mean/forecast_origin/run_id. Mean need not equal median or fall inside q10–q90. Domain checks enforce cross-field constraints beyond JSON Schema.
