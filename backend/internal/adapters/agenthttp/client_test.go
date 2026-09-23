package agenthttp

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"
	"wind/backend/api"
	"wind/backend/internal/domain"
)

func realRequest() domain.ForecastRequest {
	return domain.ForecastRequest{ForecastOrigin: time.Date(2026, 1, 31, 18, 0, 0, 0, time.UTC), HorizonHours: 24, TurbineIDs: []int{1}, ModelVersion: "test-real-protocol", Mode: "replay", DataMode: "real"}
}
func jobFixture() JobRecord {
	now := time.Date(2026, 9, 23, 10, 0, 0, 0, time.UTC)
	return JobRecord{JobID: "upstream-job", JobType: "forecast", Status: "queued", Stage: "queued", CreatedAt: now, UpdatedAt: now}
}
func testAdapter(t *testing.T, h http.HandlerFunc, edit func(*Config)) (*Adapter, *httptest.Server) {
	t.Helper()
	s := httptest.NewServer(h)
	t.Cleanup(s.Close)
	v, e := api.NewValidator()
	if e != nil {
		t.Fatal(e)
	}
	cfg := Config{BaseURL: s.URL, Token: "internal-test-token", Timeout: time.Second, ResponseLimit: 1 << 20}
	if edit != nil {
		edit(&cfg)
	}
	a, e := New(cfg, v)
	if e != nil {
		t.Fatal(e)
	}
	t.Cleanup(a.Close)
	return a, s
}
func errorCode(t *testing.T, e error, want string) {
	t.Helper()
	var de *domain.Error
	if !errors.As(e, &de) || de.Code != want {
		t.Fatalf("want %s, got %v", want, e)
	}
}
func TestCreateHeadersAndStatusMapping(t *testing.T) {
	for _, tc := range []struct {
		status int
		code   string
	}{{202, ""}, {404, "NOT_FOUND"}, {409, "IDEMPOTENCY_CONFLICT"}, {422, "VALIDATION_ERROR"}, {500, "DEPENDENCY_UNAVAILABLE"}, {503, "DEPENDENCY_UNAVAILABLE"}, {501, "FEATURE_NOT_SUPPORTED"}, {429, "RATE_LIMITED"}} {
		t.Run(http.StatusText(tc.status), func(t *testing.T) {
			var calls atomic.Int32
			a, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				if r.URL.Path != "/internal/v1/forecast-runs" || r.Header.Get("Idempotency-Key") != "stable-key" || r.Header.Get("X-Request-ID") != "req-test" || r.Header.Get("Authorization") != "Bearer internal-test-token" {
					t.Error("wrong mapping or headers")
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(tc.status)
				if tc.status == 202 {
					_ = json.NewEncoder(w).Encode(jobFixture())
				} else {
					_ = json.NewEncoder(w).Encode(ApiError{Code: "IDEMPOTENCY_CONFLICT", Message: "provider secret must never reach browser"})
				}
			}, nil)
			j, e := a.CreateForecast(context.Background(), realRequest(), domain.Operation{RequestID: "req-test", IdempotencyKey: "stable-key"})
			if tc.code == "" {
				if e != nil || j.JobID != "upstream-job" {
					t.Fatal(j, e)
				}
			} else {
				errorCode(t, e, tc.code)
				var de *domain.Error
				_ = errors.As(e, &de)
				if strings.Contains(de.Message, "secret") {
					t.Fatal("provider secret leaked")
				}
			}
			if calls.Load() != 1 {
				t.Fatal("POST retried")
			}
		})
	}
}
func TestMalformedResponsesAndTimeout(t *testing.T) {
	for name, body := range map[string]string{"html": "<html>secret</html>", "malformed": "{", "missing": `{"job_id":"x"}`, "null": "null", "enum": `{"job_id":"x","job_type":"forecast","status":"thinking","created_at":"2026-01-01T00:00:00Z","updated_at":"2026-01-01T00:00:00Z","stage":"x","error_code":null,"error_message":null}`} {
		t.Run(name, func(t *testing.T) {
			a, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(202)
				_, _ = io.WriteString(w, body)
			}, nil)
			_, e := a.CreateForecast(context.Background(), realRequest(), domain.Operation{})
			errorCode(t, e, "UPSTREAM_CONTRACT_VIOLATION")
		})
	}
	t.Run("size", func(t *testing.T) {
		a, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(202)
			_, _ = io.WriteString(w, strings.Repeat("x", 100))
		}, func(c *Config) { c.ResponseLimit = 20 })
		_, e := a.CreateForecast(context.Background(), realRequest(), domain.Operation{})
		errorCode(t, e, "UPSTREAM_CONTRACT_VIOLATION")
	})
	t.Run("timeout", func(t *testing.T) {
		a, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) {
			_, _ = io.Copy(io.Discard, r.Body)
			select {
			case <-r.Context().Done():
			case <-time.After(100 * time.Millisecond):
			}
		}, func(c *Config) { c.Timeout = 10 * time.Millisecond })
		_, e := a.CreateForecast(context.Background(), realRequest(), domain.Operation{})
		errorCode(t, e, "UPSTREAM_TIMEOUT")
	})
}
func TestSafeGetRetryAndRedirectProtection(t *testing.T) {
	var calls atomic.Int32
	a, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			w.WriteHeader(503)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(jobFixture())
	}, nil)
	j, e := a.GetJob(context.Background(), "upstream-job")
	if e != nil || j.JobID != "upstream-job" || calls.Load() != 2 {
		t.Fatal(j, e, calls.Load())
	}
	var leaked atomic.Int32
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { leaked.Add(1) }))
	defer other.Close()
	redirect, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, other.URL, 302) }, nil)
	_, e = redirect.CreateForecast(context.Background(), realRequest(), domain.Operation{})
	errorCode(t, e, "UPSTREAM_CONTRACT_VIOLATION")
	if leaked.Load() != 0 {
		t.Fatal("redirect followed with token")
	}
}
func resultFixture() ForecastResult {
	q := realRequest()
	r := ForecastResult{RunID: "upstream-job", ForecastOrigin: q.ForecastOrigin, HorizonHours: q.HorizonHours, TurbineIDs: q.TurbineIDs, DataMode: "real", ModelVersion: q.ModelVersion, FeatureVersion: "test-protocol-v1", TrainingDataAvailableThrough: q.ForecastOrigin.Add(-time.Hour), QualityStatus: "passed", ExplanationStatus: "unavailable", Warnings: []string{}, WeatherRuns: []WeatherProvenance{{Provider: "GFS", RunID: "test-archive", InitializationTime: q.ForecastOrigin.Add(-6 * time.Hour), EffectiveAvailableAt: q.ForecastOrigin.Add(-3 * time.Hour), AvailabilityBasis: "observed_publication", RetrievedAt: time.Now().UTC(), SourceReference: "https://example.test/archive", ContentSHA256: strings.Repeat("b", 64)}}, Points: []ForecastPoint{}}
	for i := 1; i <= 24; i++ {
		ts := q.ForecastOrigin.Add(time.Duration(i) * time.Hour)
		r.Points = append(r.Points, ForecastPoint{TurbineID: 1, LeadHours: i, ValidTime: ts, IntervalEnd: ts.Add(time.Hour), PowerMean: 2, Q10: -1, Q50: 0, Q90: 1})
	}
	return r
}
func TestResultPolicyAndRequestAssociation(t *testing.T) {
	for _, scenario := range []string{"valid", "future-weather", "horizon", "missing-quantile", "fixture", "wrong-id", "missing-hour"} {
		t.Run(scenario, func(t *testing.T) {
			a, _ := testAdapter(t, func(w http.ResponseWriter, r *http.Request) {
				w.Header().Set("Content-Type", "application/json")
				if !strings.HasSuffix(r.URL.Path, "/result") {
					j := jobFixture()
					j.Status = "completed"
					_ = json.NewEncoder(w).Encode(ForecastRunDetails{Job: j, Request: ForecastRequestFromDomain(realRequest()), ResultAvailable: true})
					return
				}
				v := resultFixture()
				switch scenario {
				case "future-weather":
					v.WeatherRuns[0].EffectiveAvailableAt = v.ForecastOrigin.Add(time.Hour)
				case "horizon":
					v.HorizonHours = 48
				case "fixture":
					v.DataMode = "fixture"
				case "wrong-id":
					v.RunID = "another"
				case "missing-hour":
					v.Points = v.Points[1:]
				}
				if scenario == "missing-quantile" {
					b, _ := json.Marshal(v)
					var raw map[string]any
					_ = json.Unmarshal(b, &raw)
					delete(raw["points"].([]any)[0].(map[string]any), "q10")
					_ = json.NewEncoder(w).Encode(raw)
				} else {
					_ = json.NewEncoder(w).Encode(v)
				}
			}, nil)
			r, e := a.ForecastResult(context.Background(), "upstream-job")
			if scenario == "valid" {
				if e != nil || len(r.Points) != 24 {
					t.Fatal(e)
				}
			} else {
				errorCode(t, e, "UPSTREAM_CONTRACT_VIOLATION")
			}
		})
	}
}
