package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
	"wind/backend/api"
	"wind/backend/internal/app"
	"wind/backend/internal/transport/http/dto"
)

func newServer(t *testing.T, edit func(*app.Config)) (*httptest.Server, *api.Validator) {
	t.Helper()
	cfg := app.DefaultConfig()
	cfg.StepDelay = time.Millisecond
	cfg.PollInterval = time.Millisecond
	cfg.Heartbeat = 5 * time.Millisecond
	if edit != nil {
		edit(&cfg)
	}
	a, e := app.New(cfg)
	if e != nil {
		t.Fatal(e)
	}
	s := httptest.NewServer(a.Handler)
	t.Cleanup(func() { _ = a.Shutdown(context.Background()); s.Close() })
	v, e := api.NewValidator()
	if e != nil {
		t.Fatal(e)
	}
	return s, v
}
func call(t *testing.T, s *httptest.Server, method, path, body, key string) (int, []byte, http.Header) {
	t.Helper()
	req, e := http.NewRequest(method, s.URL+path, bytes.NewBufferString(body))
	if e != nil {
		t.Fatal(e)
	}
	req.Header.Set("Content-Type", "application/json")
	if key != "" {
		req.Header.Set("Idempotency-Key", key)
	}
	resp, e := s.Client().Do(req)
	if e != nil {
		t.Fatal(e)
	}
	defer resp.Body.Close()
	b, e := io.ReadAll(resp.Body)
	if e != nil {
		t.Fatal(e)
	}
	return resp.StatusCode, b, resp.Header
}

const request = `{"forecast_origin":"2026-01-31T18:00:00Z","model_version":"fixture-not-trained","data_mode":"fixture"}`

func create(t *testing.T, s *httptest.Server, key string) dto.JobRecord {
	t.Helper()
	status, b, _ := call(t, s, "POST", "/api/forecast-runs", request, key)
	if status != 202 {
		t.Fatalf("create %d: %s", status, b)
	}
	var j dto.JobRecord
	if e := json.Unmarshal(b, &j); e != nil {
		t.Fatal(e)
	}
	return j
}
func waitJob(t *testing.T, s *httptest.Server, id string) dto.JobRecord {
	t.Helper()
	deadline := time.Now().Add(3 * time.Second)
	for time.Now().Before(deadline) {
		status, b, _ := call(t, s, "GET", "/api/jobs/"+id, "", "")
		if status != 200 {
			t.Fatalf("job %d %s", status, b)
		}
		var j dto.JobRecord
		_ = json.Unmarshal(b, &j)
		if j.Status == "completed" || j.Status == "failed" || j.Status == "cancelled" {
			return j
		}
		time.Sleep(time.Millisecond)
	}
	t.Fatal("job did not finish")
	return dto.JobRecord{}
}
func TestForecastVerticalSlice(t *testing.T) {
	s, v := newServer(t, nil)
	j := create(t, s, "first")
	if j.Status != "queued" {
		t.Fatalf("initial %s", j.Status)
	}
	j = waitJob(t, s, j.JobID)
	if j.Status != "completed" {
		t.Fatalf("terminal %+v", j)
	}
	code, b, _ := call(t, s, "GET", "/api/forecast-runs/"+j.JobID+"/result", "", "")
	if code != 200 {
		t.Fatalf("%d %s", code, b)
	}
	if e := v.Validate("ForecastResult", b); e != nil {
		t.Fatal(e)
	}
	var r dto.ForecastResult
	_ = json.Unmarshal(b, &r)
	if len(r.Points) != 96 || r.DataMode != "fixture" {
		t.Fatalf("wrong result")
	}
}
