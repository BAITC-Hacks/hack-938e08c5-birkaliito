#!/bin/sh
# Run from the build image with /src bound read-only to the current checkout.
set -eu
make build
make vet
make test
make race
make run-mock >/tmp/wind-api.log 2>&1 &
server_pid=$!
trap 'kill "$server_pid" 2>/dev/null || true' EXIT INT TERM
attempt=0
until curl --silent --fail http://127.0.0.1:8080/readyz >/dev/null; do
  attempt=$((attempt + 1))
  if [ "$attempt" -ge 60 ]; then cat /tmp/wind-api.log; exit 1; fi
  sleep 1
done
make smoke
