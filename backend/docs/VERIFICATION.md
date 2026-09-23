# Verification record — 2026-09-23

Environment inspected: Windows amd64, Go 1.25.6, Node 24.11.1, Python 3.14.0, Docker Engine 29.6.2. Dependency versions are pinned in go.mod/go.sum, TypeScript package-lock.json and Python requirements.txt.

## Completed on Windows

| Command | Result |
|---|---|
| `gofmt -w .` | Completed |
| `go mod tidy` | Completed; dependencies and sums resolved |
| `go build ./...` | Passed |
| `go vet ./...` | Passed |
| `go test ./...` | Passed, including domain, usecase, handler, HTTP/mock adapter, architecture, integration and contract snapshots |
| `python tools/generate_contract.py --check` | Passed; OpenAPI, boundary Go types/mappings and TypeScript match generation |
| `go run ./cmd/fixtures` | Generated and schema-validated 53 complete fixture snapshots |
| `go run ./cmd/smoke` | Passed against an actually running Go API: 202, idempotent retry/conflict, SSE stream_end, 96 result points and 97 CSV rows |
| `npm run typecheck` | Passed, TypeScript 5.9.3 |
| `npm ci` | Passed from the committed lockfile |
| `npm test` | 4 passed: typed errors/key propagation, SSE dedup/end, fallback polling, unmount without job cancellation |
| `.venv/Scripts/python -m unittest discover -s contracts/python -v` | 3 passed; includes all 53 snapshots and UTC/default/availability checks |
| `docker compose config --quiet` | Passed |

The initial Windows `go test -race ./...` could not run because CGO_ENABLED=0 and no GCC/Clang was found on PATH. The complete suite subsequently passed with the race detector in Linux Docker.

Sandbox restrictions initially blocked the Go build cache, Node child-process runner and Python venv ensurepip. The same operations were rerun with reviewed escalation and passed. Tests need no actual weather, real Python service, model or LLM credentials.

## Completed in Linux Docker

```powershell
docker build --target build -t wind-backend-build:local .
docker run --rm --mount 'type=bind,source=C:\Users\ACER\Desktop\hack-938e08c5-birkaliito\backend,target=/src,readonly' -w /src -e GIN_MODE=release wind-backend-build:local sh tools/container-check.sh
docker build -t wind-backend:local .
```

All commands passed. The container check ran `make build`, `make vet`, `make test`, `make race` (`go test -race ./...`), then started `make run-mock` and passed `make smoke` against it. No races were reported. The checkout was read-only inside the verification container; tests used its own writable build cache.

The final scratch runtime image also started successfully as user `65532:65532`, published temporarily on `127.0.0.1:18080`. `go run ./cmd/smoke -base http://127.0.0.1:18080` passed against this image. Re-running the image with `MOCK_SCENARIO=failure` passed `go run ./cmd/smoke -base http://127.0.0.1:18080 -expect failed`, confirming SSE termination, failed job metadata and unavailable result. Both normal compose and the HTTP overlay passed `docker compose ... config --quiet`.

These container tests verify the Go runtime and integration boundaries, not the external ML service. The image uses the source and embedded schema; no fixture JSON files or docs CDN are required at runtime.

## Coverage details

- Strict required/default/null/unknown/trailing JSON validation, wrong horizons/turbines/models, naive and misaligned timestamps, duplicate normalized replay origins, body limits and content types.
- 24/48 hours × one/two turbines, no missing/duplicate pairs, ordered finite quantiles, exact intervals and training/weather cutoffs; mean outside the interval is allowed.
- Parallel idempotent submissions, bounded admission with no orphan job, immutable result copies, cancellation/completion races, cancelled replay preserving completed children, explicit partial export.
- SSE backlog/live order, Last-Event-ID priority, validation of both cursors, retention expiry before headers, terminal close, heartbeat during blocked upstream polling, and subscription disconnect preserving the job.
- Upstream 202/404/409/422/500/503/501/429, deadlines, oversized/malformed/missing-field/invalid-enum JSON, request/result identity and horizon mismatch, missing quantiles, future weather, redirect/token protection and bounded safe GET retries.
- History sorting/cursors, real-mode dependency failure without fixture fallback, independent App stores, actual fixture weather checksum, schema-validated read models, UTC CSV without deduplicating overlapping runs.

## External integration limits

No actual Python/CatBoost/LangGraph service or real weather/SCADA artifacts were supplied. HTTP adapter tests use local controlled httptest servers. Real model connectivity, model accuracy, real SHAP, real audit/evaluation reports, archived GFS provenance and persistent Python job/checkpoint recovery remain external integration work. Mock SHAP truthfully reports unavailable. Mock persistence ends at process restart.
