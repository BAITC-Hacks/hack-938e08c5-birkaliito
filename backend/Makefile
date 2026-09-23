.PHONY: run-mock run-http build test vet race check smoke fixtures generate typecheck
run-mock: export AGENT_MODE=mock
run-mock: export ALLOW_FIXTURES=true
run-mock:
	go run ./cmd/api
run-http: export AGENT_MODE=http
run-http: export ALLOW_FIXTURES=false
run-http:
	go run ./cmd/api
build:
	go build ./...
test:
	go test ./...
vet:
	go vet ./...
race:
	go test -race ./...
check: build vet test
smoke:
	go run ./cmd/smoke
fixtures:
	go run ./cmd/fixtures
generate:
	python tools/generate_contract.py
	gofmt -w .
typecheck:
	cd contracts/typescript && npm ci && npm run typecheck
