# hack-938e08c5-birkaliito

Hackathon team repository for Birkaliito.

## Backend

Go/Gin Wind Forecast backend: [backend/README.md](backend/README.md).

Start from `backend/` with `go run ./cmd/api`, then `go run ./cmd/smoke` in a
second terminal. API docs: `http://127.0.0.1:8080/docs`. Default mode is
explicitly synthetic fixture simulation; Python integration is configured
separately.

Frontend integration package: [handoff](backend/docs/FRONTEND_HANDOFF.md),
[OpenAPI](backend/api/openapi.yaml), and
[TypeScript client](backend/contracts/typescript/client.ts).

## Interactive AURA design

The responsive prototype covers forecasts, hourly analytics, energy scenarios,
history, replay, quality, agent sources, source data, and the forecast passport.

```bash
cd design
go run main.go
```

Open `http://localhost:4173/#forecast`. Run the presentation-model tests with
`node --test design/model.test.mjs` from the repository root.

See [the UX and design-system specification](design/DESIGN.md).
