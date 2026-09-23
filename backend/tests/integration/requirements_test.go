package integration

import (
	"context"
	"crypto/sha256"
	"encoding/csv"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"testing"
	"time"
	"wind/backend/internal/app"
	"wind/backend/internal/transport/http/dto"
)

func TestFixtureWeatherChecksum(t *testing.T) {
	s, _ := newServer(t, nil)
	j := waitJob(t, s, create(t, s, "weather-checksum").JobID)
	code, b, _ := call(t, s, "GET", "/api/forecast-runs/"+j.JobID+"/weather", "", "")
	if code != 200 {
		t.Fatal(code)
	}
	var value map[string]any
	_ = json.Unmarshal(b, &value)
	artifact, _ := json.Marshal(value["points"])
	hash := sha256.Sum256(artifact)
	provenance := value["weather_runs"].([]any)[0].(map[string]any)
	if provenance["content_sha256"] != hex.EncodeToString(hash[:]) {
		t.Fatal("checksum not tied to returned fixture artifact")
	}
}
func TestHTTPUnavailableIsNotMockFallback(t *testing.T) {
	s, v := newServer(t, func(c *app.Config) {
		c.AgentMode = "http"
		c.AllowFixtures = false
		c.PythonBaseURL = "http://127.0.0.1:1"
		c.UpstreamTimeout = 100 * time.Millisecond
	})
	code, b, _ := call(t, s, "GET", "/api/meta", "", "")
	if code != 200 {
		t.Fatal(code)
	}
	if e := v.Validate("Meta", b); e != nil {
		t.Fatal(e)
	}
	var meta dto.Meta
	_ = json.Unmarshal(b, &meta)
	if meta.AgentDependency != "unavailable" || meta.Capabilities.Simulated || meta.Capabilities.Forecast {
		t.Fatal("invented available capability")
	}
	body := strings.ReplaceAll(strings.ReplaceAll(request, "fixture-not-trained", "real-model"), `"data_mode":"fixture"`, `"data_mode":"real"`)
	code, b, _ = call(t, s, "POST", "/api/forecast-runs", body, "real")
	if code != 503 && code != 504 {
		t.Fatalf("unavailable Python invented job: %d %s", code, b)
	}
	code, _, _ = call(t, s, "POST", "/api/forecast-runs", request, "fixture-disabled")
	if code != 403 {
		t.Fatal("fixtures permitted in http mode")
	}
}

func TestExpiredEventCursorBeforeSSEHeaders(t *testing.T) {
	s, _ := newServer(t, func(c *app.Config) { c.MaxEvents = 2 })
	j := waitJob(t, s, create(t, s, "retained").JobID)
	for _, suffix := range []string{"events", "stream"} {
		code, b, headers := call(t, s, "GET", "/api/jobs/"+j.JobID+"/"+suffix+"?after=0", "", "")
		if code != 410 || !strings.HasPrefix(headers.Get("Content-Type"), "application/json") {
			t.Fatalf("%d %s", code, b)
		}
	}
	code, _, _ := call(t, s, "GET", "/api/jobs/"+j.JobID+"/events?after=9999", "", "")
	if code != 400 {
		t.Fatal("future cursor accepted")
	}
}
func TestRequestValidation(t *testing.T) {
	s, _ := newServer(t, nil)
	cases := []struct {
		name, body string
		status     int
	}{{"unknown", strings.TrimSuffix(request, "}") + `,"scenario":"failure"}`, 422}, {"null", strings.TrimSuffix(request, "}") + `,"horizon_hours":null}`, 422}, {"zero", strings.TrimSuffix(request, "}") + `,"horizon_hours":0}`, 422}, {"horizon", strings.TrimSuffix(request, "}") + `,"horizon_hours":25}`, 422}, {"turbines", strings.TrimSuffix(request, "}") + `,"turbine_ids":[1,1]}`, 422}, {"empty model", strings.Replace(request, "fixture-not-trained", "", 1), 422}, {"naive time", strings.Replace(request, "18:00:00Z", "18:00:00", 1), 422}, {"half hour", strings.Replace(request, "18:00:00Z", "18:30:00Z", 1), 422}, {"trailing", request + ` {}`, 400}, {"missing", `{}`, 422}, {"default real", `{"forecast_origin":"2026-01-31T18:00:00Z","model_version":"fixture-not-trained"}`, 422}}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			code, b, h := call(t, s, "POST", "/api/forecast-runs", tc.body, "validation-"+strings.ReplaceAll(tc.name, " ", "-"))
			if code != tc.status {
				t.Fatalf("%d %s", code, b)
			}
			var e dto.ApiError
			_ = json.Unmarshal(b, &e)
			if e.RequestID == nil || *e.RequestID != h.Get("X-Request-ID") {
				t.Fatal("request id missing")
			}
		})
	}
	code, _, _ := call(t, s, "POST", "/api/forecast-runs", request, "")
	if code != 422 {
		t.Fatal("missing key accepted")
	}
	body := `{"origins":["2026-01-31T18:00:00Z","2026-01-31T23:00:00+05:00"],"model_version":"fixture-not-trained","data_mode":"fixture"}`
	code, b, _ := call(t, s, "POST", "/api/replays", body, "duplicate-origins")
	if code != 422 {
		t.Fatalf("%d %s", code, b)
	}
}
func TestIdempotencyDefaultsAndUTC(t *testing.T) {
	s, _ := newServer(t, nil)
	first := create(t, s, "same")
	equivalent := `{"forecast_origin":"2026-01-31T23:00:00+05:00","horizon_hours":48,"turbine_ids":[2,1],"mode":"replay","data_mode":"fixture","model_version":"fixture-not-trained"}`
	code, b, _ := call(t, s, "POST", "/api/forecast-runs", equivalent, "same")
	var second dto.JobRecord
	_ = json.Unmarshal(b, &second)
	if code != 202 || first.JobID != second.JobID {
		t.Fatalf("%d %s", code, b)
	}
	code, _, _ = call(t, s, "POST", "/api/forecast-runs", strings.Replace(equivalent, `"horizon_hours":48`, `"horizon_hours":24`, 1), "same")
	if code != 409 {
		t.Fatal("conflict not reported")
	}
}
func TestResultShapesAndImmutability(t *testing.T) {
	s, v := newServer(t, nil)
	for _, h := range []int{24, 48} {
		for _, ids := range []string{"[1]", "[2]", "[1,2]"} {
			body := strings.TrimSuffix(request, "}") + fmt.Sprintf(`,"horizon_hours":%d,"turbine_ids":%s}`, h, ids)
			code, b, _ := call(t, s, "POST", "/api/forecast-runs", body, fmt.Sprintf("shape-%d-%s", h, strings.ReplaceAll(ids, ",", "-")))
			if code != 202 {
				t.Fatalf("%d %s", code, b)
			}
			var j dto.JobRecord
			_ = json.Unmarshal(b, &j)
			waitJob(t, s, j.JobID)
			_, b, _ = call(t, s, "GET", "/api/forecast-runs/"+j.JobID+"/result", "", "")
			if e := v.Validate("ForecastResult", b); e != nil {
				t.Fatal(e)
			}
			_, again, _ := call(t, s, "GET", "/api/forecast-runs/"+j.JobID+"/result", "", "")
			if string(b) != string(again) {
				t.Fatal("published result changed")
			}
		}
	}
}
func TestSSEBacklogResumeAndCancellation(t *testing.T) {
	s, v := newServer(t, nil)
	j := create(t, s, "stream")
	url := s.URL + "/api/jobs/" + j.JobID + "/stream"
	resp, e := s.Client().Get(url)
	if e != nil {
		t.Fatal(e)
	}
	b, e := io.ReadAll(resp.Body)
	resp.Body.Close()
	if e != nil || resp.StatusCode != 200 {
		t.Fatalf("%v %d %s", e, resp.StatusCode, b)
	}
	if !strings.Contains(string(b), "event: stream_end") || !strings.Contains(string(b), "event: agent_event") {
		t.Fatal(string(b))
	}
	if resp.Header.Get("X-Accel-Buffering") != "no" {
		t.Fatal("buffering")
	}
	var last int64
	for _, block := range strings.Split(string(b), "\n\n") {
		if strings.Contains(block, "event: agent_event") {
			lines := strings.Split(block, "\n")
			raw := strings.TrimPrefix(lines[2], "data: ")
			if e = v.Validate("AgentEvent", []byte(raw)); e != nil {
				t.Fatal(e)
			}
			var ev dto.AgentEvent
			_ = json.Unmarshal([]byte(raw), &ev)
			if ev.EventID <= last {
				t.Fatal("unordered SSE")
			}
			last = ev.EventID
		}
	}
	req, _ := http.NewRequest("GET", url+"?after=0", nil)
	req.Header.Set("Last-Event-ID", fmt.Sprint(last))
	resp, e = s.Client().Do(req)
	if e != nil {
		t.Fatal(e)
	}
	b, _ = io.ReadAll(resp.Body)
	resp.Body.Close()
	if strings.Contains(string(b), "event: agent_event") || !strings.Contains(string(b), "stream_end") {
		t.Fatal(string(b))
	}
	req, _ = http.NewRequest("GET", url+"?after=invalid", nil)
	req.Header.Set("Last-Event-ID", fmt.Sprint(last))
	resp, e = s.Client().Do(req)
	if e != nil {
		t.Fatal(e)
	}
	resp.Body.Close()
	if resp.StatusCode != 400 {
		t.Fatal("both cursor sources must validate")
	}
	code, _, _ := call(t, s, "POST", "/api/jobs/"+j.JobID+"/cancel", "", "")
	if code != 409 {
		t.Fatal("completed cancellation allowed")
	}
	slow, _ := newServer(t, func(c *app.Config) { c.StepDelay = 20 * time.Millisecond })
	j = create(t, slow, "disconnect")
	ctx, cancel := context.WithCancel(context.Background())
	req, _ = http.NewRequestWithContext(ctx, "GET", slow.URL+"/api/jobs/"+j.JobID+"/stream", nil)
	resp, e = slow.Client().Do(req)
	if e != nil {
		t.Fatal(e)
	}
	cancel()
	resp.Body.Close()
	j = waitJob(t, slow, j.JobID)
	if j.Status != "completed" {
		t.Fatal("disconnect cancelled forecast")
	}
}
func TestReplayAndCSV(t *testing.T) {
	s, v := newServer(t, nil)
	body := `{"origins":["2026-01-31T18:00:00Z","2026-02-01T18:00:00Z"],"model_version":"fixture-not-trained","data_mode":"fixture"}`
	code, b, _ := call(t, s, "POST", "/api/replays", body, "replay")
	if code != 202 {
		t.Fatalf("%d %s", code, b)
	}
	var j dto.JobRecord
	_ = json.Unmarshal(b, &j)
	j = waitJob(t, s, j.JobID)
	if j.Status != "completed" {
		t.Fatal(j)
	}
	code, b, _ = call(t, s, "GET", "/api/replays/"+j.JobID, "", "")
	if code != 200 {
		t.Fatal(code)
	}
	if e := v.Validate("ReplayDetails", b); e != nil {
		t.Fatal(e)
	}
	var d dto.ReplayDetails
	_ = json.Unmarshal(b, &d)
	if d.Counters.Completed != 2 || d.Counters.Total != 2 {
		t.Fatal(d.Counters)
	}
	code, b, headers := call(t, s, "GET", "/api/replays/"+j.JobID+"/export", "", "")
	if code != 200 || headers.Get("X-Replay-Export-Status") != "complete" {
		t.Fatalf("%d %s", code, b)
	}
	rows, e := csv.NewReader(strings.NewReader(string(b))).ReadAll()
	if e != nil || len(rows) != 193 {
		t.Fatalf("rows %d %v", len(rows), e)
	}
	for _, row := range rows[1:] {
		if row[10] != "fixture" || !strings.HasSuffix(row[1], "Z") {
			t.Fatal(row)
		}
	}
	if rows[1][0] == rows[97][0] {
		t.Fatal("overlapping runs collapsed")
	}
	reversed := `{"origins":["2026-02-01T18:00:00Z","2026-01-31T18:00:00Z"],"model_version":"fixture-not-trained","data_mode":"fixture"}`
	code, b, _ = call(t, s, "POST", "/api/replays", reversed, "replay")
	var same dto.JobRecord
	_ = json.Unmarshal(b, &same)
	if code != 202 || same.JobID != j.JobID {
		t.Fatal("replay fingerprint sorting")
	}
}
func TestScenariosAndPartialReplay(t *testing.T) {
	for _, scenario := range []string{"degraded", "failure", "llm_unavailable", "weather_future"} {
		t.Run(scenario, func(t *testing.T) {
			s, v := newServer(t, func(c *app.Config) { c.MockScenario = scenario })
			j := waitJob(t, s, create(t, s, "scenario").JobID)
			expected := "completed"
			if scenario == "failure" || scenario == "weather_future" {
				expected = "failed"
			}
			if j.Status != expected {
				t.Fatal(j)
			}
			code, b, _ := call(t, s, "GET", "/api/forecast-runs/"+j.JobID+"/result", "", "")
			if expected == "failed" {
				if code != 409 {
					t.Fatal(code)
				}
			} else {
				if e := v.Validate("ForecastResult", b); e != nil {
					t.Fatal(e)
				}
				var r dto.ForecastResult
				_ = json.Unmarshal(b, &r)
				if scenario == "degraded" && r.QualityStatus != "degraded" {
					t.Fatal(r.QualityStatus)
				}
				if scenario == "llm_unavailable" && r.ExplanationStatus != "unavailable" {
					t.Fatal(r.ExplanationStatus)
				}
			}
		})
	}
	s, _ := newServer(t, func(c *app.Config) { c.StepDelay = time.Second; c.Workers = 1 })
	body := `{"origins":["2026-01-31T18:00:00Z","2026-02-01T18:00:00Z"],"model_version":"fixture-not-trained","data_mode":"fixture"}`
	_, b, _ := call(t, s, "POST", "/api/replays", body, "cancel-replay")
	var j dto.JobRecord
	_ = json.Unmarshal(b, &j)
	code, _, _ := call(t, s, "POST", "/api/jobs/"+j.JobID+"/cancel", "", "")
	if code != 200 && code != 202 {
		t.Fatal(code)
	}
	j = waitJob(t, s, j.JobID)
	if j.Status != "cancelled" {
		t.Fatal(j)
	}
	code, _, _ = call(t, s, "GET", "/api/replays/"+j.JobID+"/export", "", "")
	if code != 409 {
		t.Fatal("partial silently exported")
	}
	code, _, headers := call(t, s, "GET", "/api/replays/"+j.JobID+"/export?allow_partial=true", "", "")
	if code != 200 || headers.Get("X-Replay-Export-Status") != "partial" {
		t.Fatal(code, headers)
	}
}
func TestCatalogSchemaListsIsolationAndLimits(t *testing.T) {
	s, v := newServer(t, nil)
	for path, schema := range map[string]string{"/api/meta": "Meta", "/api/models": "ModelList", "/api/turbines": "TurbineList", "/api/evaluations": "EvaluationList", "/api/evaluations/fixture-evaluation-001": "EvaluationReport", "/api/evaluations/fixture-evaluation-unavailable": "EvaluationReport", "/api/data-quality": "DataQualityReport", "/api/forecast-runs": "ForecastList"} {
		code, b, _ := call(t, s, "GET", path, "", "")
		if code != 200 {
			t.Fatalf("%s: %d %s", path, code, b)
		}
		if e := v.Validate(schema, b); e != nil {
			t.Fatal(path, e)
		}
	}
	j := waitJob(t, s, create(t, s, "details").JobID)
	for suffix, schema := range map[string]string{"": "ForecastRunDetails", "/weather": "WeatherDetails", "/explanation": "ExplanationDetails"} {
		code, b, _ := call(t, s, "GET", "/api/forecast-runs/"+j.JobID+suffix, "", "")
		if code != 200 {
			t.Fatal(code)
		}
		if e := v.Validate(schema, b); e != nil {
			t.Fatal(e)
		}
	}
	other, _ := newServer(t, nil)
	code, _, _ := call(t, other, "GET", "/api/jobs/"+j.JobID, "", "")
	if code != 404 {
		t.Fatal("global store leaked")
	}
	create(t, s, "second")
	_, b, _ := call(t, s, "GET", "/api/forecast-runs?limit=1", "", "")
	var page dto.ForecastList
	_ = json.Unmarshal(b, &page)
	if len(page.Items) != 1 || page.NextCursor == nil {
		t.Fatal(string(b))
	}
	code, b, _ = call(t, s, "GET", "/api/forecast-runs?limit=1&cursor="+*page.NextCursor, "", "")
	if code != 200 {
		t.Fatal(string(b))
	}
	code, _, _ = call(t, s, "GET", "/api/forecast-runs?limit=1&status=completed&cursor="+*page.NextCursor, "", "")
	if code != 400 {
		t.Fatal("unbound cursor")
	}
	for _, q := range []string{"?limit=0", "?limit=101", "?cursor=garbage", "?status=wat", "?forecast_origin_from=2026-02-01T00:00:00Z&forecast_origin_to=2026-01-01T00:00:00Z", "?limit=1&limit=2"} {
		code, _, _ = call(t, s, "GET", "/api/forecast-runs"+q, "", "")
		if code != 400 && code != 422 {
			t.Fatal(q, code)
		}
	}
	limited, _ := newServer(t, func(c *app.Config) { c.BodyLimit = 16 })
	code, _, _ = call(t, limited, "POST", "/api/forecast-runs", request, "limit")
	if code != 413 {
		t.Fatal(code)
	}
	req, _ := http.NewRequest("POST", s.URL+"/api/forecast-runs", strings.NewReader(request))
	req.Header.Set("Content-Type", "text/plain")
	resp, e := s.Client().Do(req)
	if e != nil {
		t.Fatal(e)
	}
	resp.Body.Close()
	if resp.StatusCode != 415 {
		t.Fatal(resp.StatusCode)
	}
}
