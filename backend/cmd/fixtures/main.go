// Regenerates synthetic examples by calling the actual in-process HTTP application.
package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"time"
	"wind/backend/api"
	"wind/backend/internal/app"
	"wind/backend/internal/transport/http/dto"
)

type generator struct {
	app       *app.App
	validator *api.Validator
	manifest  map[string]string
}

func (g *generator) call(method, path, body, key string) *httptest.ResponseRecorder {
	r := httptest.NewRequest(method, path, bytes.NewBufferString(body))
	r.Header.Set("Content-Type", "application/json")
	r.Header.Set("Idempotency-Key", key)
	r.Header.Set("X-Request-ID", "req-fixture-example")
	w := httptest.NewRecorder()
	g.app.Handler.ServeHTTP(w, r)
	return w
}
func (g *generator) save(name, schema string, w *httptest.ResponseRecorder) {
	if w.Code >= 400 && schema != "ApiError" {
		panic(fmt.Sprintf("%s %d %s", name, w.Code, w.Body.String()))
	}
	var value any
	if e := json.Unmarshal(w.Body.Bytes(), &value); e != nil {
		panic(e)
	}
	if len(schema) > 2 && schema[len(schema)-2:] == "[]" {
		for _, v := range value.([]any) {
			b, _ := json.Marshal(v)
			if e := g.validator.Validate(schema[:len(schema)-2], b); e != nil {
				panic(e)
			}
		}
	} else if e := g.validator.Validate(schema, w.Body.Bytes()); e != nil {
		panic(e)
	}
	b, _ := json.MarshalIndent(value, "", "  ")
	file := name + ".fixture.json"
	if e := os.WriteFile(filepath.Join("testdata", "fixtures", file), append(b, '\n'), 0644); e != nil {
		panic(e)
	}
	g.manifest[file] = schema
}
func (g *generator) await(id string) dto.JobRecord {
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		w := g.call("GET", "/api/jobs/"+id, "", "")
		var j dto.JobRecord
		_ = json.Unmarshal(w.Body.Bytes(), &j)
		if j.Status == "completed" || j.Status == "failed" || j.Status == "cancelled" {
			return j
		}
		time.Sleep(time.Millisecond)
	}
	panic("fixture job timeout")
}
func main() {
	if e := os.MkdirAll("testdata/fixtures", 0755); e != nil {
		panic(e)
	}
	v, e := api.NewValidator()
	if e != nil {
		panic(e)
	}
	g := &generator{validator: v, manifest: map[string]string{}}
	for _, scenario := range []string{"success", "degraded", "failure", "llm_unavailable", "weather_future", "slow"} {
		cfg := app.DefaultConfig()
		cfg.LogLevel = slog.LevelError
		cfg.MockScenario = scenario
		cfg.StepDelay = time.Millisecond
		if scenario == "slow" {
			cfg.StepDelay = time.Second
		}
		a, e := app.New(cfg)
		if e != nil {
			panic(e)
		}
		g.app = a
		if scenario == "success" {
			for path, schema := range map[string]string{"meta": "Meta", "models": "ModelList", "turbines": "TurbineList", "evaluations": "EvaluationList", "data-quality": "DataQualityReport"} {
				g.save(path, schema, g.call("GET", "/api/"+path, "", ""))
			}
			g.save("history-empty", "ForecastList", g.call("GET", "/api/forecast-runs", "", ""))
			g.save("metrics-unavailable", "EvaluationReport", g.call("GET", "/api/evaluations/fixture-evaluation-unavailable", "", ""))
		}
		body := `{"forecast_origin":"2026-01-31T18:00:00Z","model_version":"fixture-not-trained","data_mode":"fixture"}`
		w := g.call("POST", "/api/forecast-runs", body, "fixture-demo")
		g.save(scenario+"-queued", "JobRecord", w)
		var j dto.JobRecord
		_ = json.Unmarshal(w.Body.Bytes(), &j)
		if scenario == "slow" {
			for i := 0; i < 100; i++ {
				w = g.call("GET", "/api/jobs/"+j.JobID, "", "")
				var current dto.JobRecord
				_ = json.Unmarshal(w.Body.Bytes(), &current)
				if current.Status == "running" {
					g.save("running", "JobRecord", w)
					break
				}
				time.Sleep(time.Millisecond)
			}
			g.call("POST", "/api/jobs/"+j.JobID+"/cancel", "", "")
		}
		j = g.await(j.JobID)
		g.save(scenario+"-job", "JobRecord", g.call("GET", "/api/jobs/"+j.JobID, "", ""))
		g.save(scenario+"-events", "AgentEvent[]", g.call("GET", "/api/jobs/"+j.JobID+"/events", "", ""))
		g.save(scenario+"-details", "ForecastRunDetails", g.call("GET", "/api/forecast-runs/"+j.JobID, "", ""))
		if j.Status == "completed" {
			for suffix, schema := range map[string]string{"result": "ForecastResult", "weather": "WeatherDetails", "explanation": "ExplanationDetails"} {
				g.save(scenario+"-"+suffix, schema, g.call("GET", "/api/forecast-runs/"+j.JobID+"/"+suffix, "", ""))
			}
		} else {
			g.save(scenario+"-result-error", "ApiError", g.call("GET", "/api/forecast-runs/"+j.JobID+"/result", "", ""))
		}
		if scenario == "success" {
			g.save("forecast-request", "ForecastRequest", recorderJSON(body))
			for _, shape := range []struct{ name, extra string }{{"24-one", `,"horizon_hours":24,"turbine_ids":[1]`}, {"24-two", `,"horizon_hours":24,"turbine_ids":[1,2]`}, {"48-one", `,"horizon_hours":48,"turbine_ids":[2]`}} {
				w = g.call("POST", "/api/forecast-runs", body[:len(body)-1]+shape.extra+"}", shape.name)
				_ = json.Unmarshal(w.Body.Bytes(), &j)
				g.await(j.JobID)
				g.save(shape.name+"-result", "ForecastResult", g.call("GET", "/api/forecast-runs/"+j.JobID+"/result", "", ""))
			}
			replay := `{"origins":["2026-01-31T18:00:00Z","2026-02-01T18:00:00Z"],"model_version":"fixture-not-trained","data_mode":"fixture"}`
			g.save("replay-request", "ReplayRequest", recorderJSON(replay))
			w = g.call("POST", "/api/replays", replay, "fixture-replay")
			_ = json.Unmarshal(w.Body.Bytes(), &j)
			g.await(j.JobID)
			g.save("replay-details", "ReplayDetails", g.call("GET", "/api/replays/"+j.JobID, "", ""))
			g.save("replay-runs", "JobRecord[]", g.call("GET", "/api/replays/"+j.JobID+"/runs", "", ""))
			g.save("history", "ForecastList", g.call("GET", "/api/forecast-runs", "", ""))
		}
		_ = a.Shutdown(context.Background())
	}
	unavailable := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { w.WriteHeader(503) }))
	cfg := app.DefaultConfig()
	cfg.AgentMode = "http"
	cfg.AllowFixtures = false
	cfg.PythonBaseURL = unavailable.URL
	cfg.LogLevel = slog.LevelError
	g.app, e = app.New(cfg)
	if e != nil {
		panic(e)
	}
	g.save("dependency-unavailable", "ApiError", g.call("GET", "/readyz", "", ""))
	_ = g.app.Shutdown(context.Background())
	unavailable.Close()
	b, _ := json.MarshalIndent(g.manifest, "", "  ")
	if e = os.WriteFile("testdata/fixtures/manifest.json", append(b, '\n'), 0644); e != nil {
		panic(e)
	}
	fmt.Printf("Generated and schema-validated %d fixture examples\n", len(g.manifest))
}
func recorderJSON(body string) *httptest.ResponseRecorder {
	r := httptest.NewRecorder()
	r.Code = 200
	r.Body.WriteString(body)
	return r
}
