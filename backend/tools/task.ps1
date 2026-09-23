param([ValidateSet('run-mock','run-http','build','test','vet','race','smoke','fixtures','typecheck')][string]$Task='test')
$ErrorActionPreference='Stop'
Push-Location (Split-Path $PSScriptRoot -Parent)
try {
  switch ($Task) {
    'run-mock' { $env:AGENT_MODE='mock'; $env:ALLOW_FIXTURES='true'; go run ./cmd/api }
    'run-http' { $env:AGENT_MODE='http'; $env:ALLOW_FIXTURES='false'; go run ./cmd/api }
    'build' { go build ./... }
    'test' { go test ./... }
    'vet' { go vet ./... }
    'race' { go test -race ./... }
    'smoke' { go run ./cmd/smoke }
    'fixtures' { go run ./cmd/fixtures }
    'typecheck' { Push-Location contracts/typescript; try { npm ci; if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }; npm run typecheck } finally { Pop-Location } }
  }
  exit $LASTEXITCODE
} finally { Pop-Location }
