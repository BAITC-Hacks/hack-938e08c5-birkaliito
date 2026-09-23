package main

import (
	"bytes"
	"encoding/csv"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"net/http"
	"os"
	"strings"
	"time"
	"wind/backend/api"
	"wind/backend/internal/transport/http/dto"
)

func main() {
	if e := run(); e != nil {
		fmt.Fprintln(os.Stderr, e)
		os.Exit(1)
	}
}
func run() error {
	base := flag.String("base", "http://127.0.0.1:8080", "Go API base URL")
	expected := flag.String("expect", "completed", "Expected terminal state (completed or failed)")
	flag.Parse()
	v, e := api.NewValidator()
	if e != nil {
		return e
	}
	client := &http.Client{Timeout: 15 * time.Second}
	key := fmt.Sprintf("smoke-%d", time.Now().UnixNano())
	call := func(method, path, body string) (int, []byte, error) {
		r, e := http.NewRequest(method, strings.TrimRight(*base, "/")+path, bytes.NewBufferString(body))
		if e != nil {
			return 0, nil, e
		}
		r.Header.Set("Content-Type", "application/json")
		r.Header.Set("Idempotency-Key", key)
		resp, e := client.Do(r)
		if e != nil {
			return 0, nil, e
		}
		defer resp.Body.Close()
		b, e := io.ReadAll(resp.Body)
		return resp.StatusCode, b, e
	}
	code, b, e := call("GET", "/api/meta", "")
	if e != nil {
		return e
	}
	if code != 200 {
		return fmt.Errorf("meta %d %s", code, b)
	}
	if e = v.Validate("Meta", b); e != nil {
		return e
	}
	var meta dto.Meta
	_ = json.Unmarshal(b, &meta)
	if meta.AgentMode != "mock" {
		return fmt.Errorf("smoke requires explicit mock mode")
	}
	body := `{"forecast_origin":"2026-01-31T18:00:00Z","model_version":"fixture-not-trained","data_mode":"fixture"}`
	code, b, e = call("POST", "/api/forecast-runs", body)
	if e != nil {
		return e
	}
	if code != 202 {
		return fmt.Errorf("create %d %s", code, b)
	}
	if e = v.Validate("JobRecord", b); e != nil {
		return e
	}
	var j dto.JobRecord
	_ = json.Unmarshal(b, &j)
	code, b, e = call("POST", "/api/forecast-runs", body)
	if e != nil {
		return e
	}
	var repeated dto.JobRecord
	_ = json.Unmarshal(b, &repeated)
	if code != 202 || repeated.JobID != j.JobID {
		return fmt.Errorf("idempotent retry failed")
	}
	code, _, e = call("POST", "/api/forecast-runs", strings.Replace(body, "18:00:00Z", "19:00:00Z", 1))
	if e != nil {
		return e
	}
	if code != 409 {
		return fmt.Errorf("idempotency conflict expected, got %d", code)
	}
	code, b, e = call("GET", "/api/jobs/"+j.JobID+"/stream", "")
	if e != nil {
		return e
	}
	if code != 200 || !strings.Contains(string(b), "event: stream_end") {
		return fmt.Errorf("SSE failed: %d %s", code, b)
	}
	code, b, e = call("GET", "/api/jobs/"+j.JobID, "")
	if e != nil {
		return e
	}
	if code != 200 {
		return fmt.Errorf("job %d", code)
	}
	_ = json.Unmarshal(b, &j)
	if j.Status != *expected {
		return fmt.Errorf("wanted %s, got %s", *expected, j.Status)
	}
	code, b, e = call("GET", "/api/forecast-runs/"+j.JobID+"/result", "")
	if e != nil {
		return e
	}
	if *expected == "failed" {
		if code != 409 {
			return fmt.Errorf("failed job exposed result")
		}
		fmt.Println("PASS: meta, create, idempotent retry/conflict, SSE, failed job and unavailable result")
		return nil
	}
	if code != 200 {
		return fmt.Errorf("result %d %s", code, b)
	}
	if e = v.Validate("ForecastResult", b); e != nil {
		return e
	}
	var r dto.ForecastResult
	_ = json.Unmarshal(b, &r)
	if r.DataMode != "fixture" || len(r.Points) != 96 {
		return fmt.Errorf("wrong fixture shape")
	}
	code, b, e = call("GET", "/api/forecast-runs/"+j.JobID+"/export", "")
	if e != nil {
		return e
	}
	rows, e := csv.NewReader(strings.NewReader(string(b))).ReadAll()
	if code != 200 || e != nil || len(rows) != 97 {
		return fmt.Errorf("CSV failed: %d rows=%d %v", code, len(rows), e)
	}
	fmt.Println("PASS: meta, 202 job, idempotent retry/conflict, SSE stream_end, 96 schema-validated fixture points, 97 CSV rows")
	return nil
}
