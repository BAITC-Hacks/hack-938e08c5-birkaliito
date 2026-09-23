# hack-938e08c5-birkaliito
Hackathon team repository for Birkaliito

Go/Gin Wind Forecast backend: [backend/README.md](backend/README.md).

Start from `backend/` with `go run ./cmd/api`, then `go run ./cmd/smoke` in a second terminal. API docs: `http://127.0.0.1:8080/docs`. Default mode is explicitly synthetic fixture simulation; Python integration is configured separately.

Frontend integration package: [handoff](backend/docs/FRONTEND_HANDOFF.md), [OpenAPI](backend/api/openapi.yaml), [TypeScript client](backend/contracts/typescript/client.ts).
