package handlers

import (
	"bytes"
	"context"
	"encoding/json"
	"github.com/gin-gonic/gin"
	"net/http/httptest"
	"testing"
	"wind/backend/api"
	"wind/backend/internal/domain"
)

// This fake implements only the incoming usecase, with no adapter/repository dependencies.
type fakeForecast struct {
	calls int
	fail  error
}

func (f *fakeForecast) Create(context.Context, domain.ForecastRequest, domain.Operation) (domain.JobRecord, error) {
	f.calls++
	return domain.JobRecord{JobID: "test-job"}, f.fail
}
func (f *fakeForecast) Details(context.Context, string) (domain.ForecastRunDetails, error) {
	return domain.ForecastRunDetails{}, f.fail
}
func (f *fakeForecast) Result(context.Context, string) (domain.ForecastResult, error) {
	return domain.ForecastResult{}, f.fail
}
func (f *fakeForecast) List(context.Context, domain.ListFilter) (domain.ForecastList, error) {
	return domain.ForecastList{}, f.fail
}
func (f *fakeForecast) Weather(context.Context, string) (domain.WeatherDetails, error) {
	return domain.WeatherDetails{}, f.fail
}
func (f *fakeForecast) Explanation(context.Context, string) (domain.ExplanationDetails, error) {
	return domain.ExplanationDetails{}, f.fail
}
func TestHandlerOnlyNeedsUseCase(t *testing.T) {
	v, e := api.NewValidator()
	if e != nil {
		t.Fatal(e)
	}
	fake := &fakeForecast{fail: domain.Err("QUEUE_FULL", "Queue full")}
	h := NewForecastHandler(fake, Input{v, 1024})
	r := gin.New()
	r.Use(func(c *gin.Context) { c.Set("request_id", "req-handler") })
	r.POST("/forecast", h.Create)
	req := httptest.NewRequest("POST", "/forecast", bytes.NewBufferString(`{"forecast_origin":"2026-01-31T18:00:00Z","model_version":"test"}`))
	req.Header.Set("Content-Type", "application/json")
	w := httptest.NewRecorder()
	r.ServeHTTP(w, req)
	if w.Code != 503 || fake.calls != 1 {
		t.Fatal(w.Code, fake.calls)
	}
	var body map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &body)
	if body["code"] != "QUEUE_FULL" || body["request_id"] != "req-handler" || len(body) != 3 {
		t.Fatal(body)
	}
}
