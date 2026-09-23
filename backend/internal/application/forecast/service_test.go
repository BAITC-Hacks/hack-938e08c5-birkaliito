package forecast

import (
	"context"
	"testing"
	"time"
	"wind/backend/internal/domain"
)

type fake struct {
	calls   int
	request domain.ForecastRequest
}

func (f *fake) Now() time.Time                            { return time.Now() }
func (f *fake) Wait(context.Context, time.Duration) error { return nil }
func (f *fake) Models(context.Context) (domain.ModelList, error) {
	return domain.ModelList{Items: []domain.Model{{ModelVersion: "fixture-not-trained", DataMode: "fixture", Availability: "ready", SupportsQuantiles: true, TrainingDataAvailableThrough: time.Date(2023, 1, 1, 0, 0, 0, 0, time.UTC)}}}, nil
}
func (f *fake) Capabilities(context.Context) (domain.Capabilities, error) {
	return domain.Capabilities{Forecast: true}, nil
}
func (f *fake) Ready(context.Context) error { return nil }
func (f *fake) CreateForecast(_ context.Context, q domain.ForecastRequest, _ domain.Operation) (domain.JobRecord, error) {
	f.calls++
	f.request = q
	now := time.Now()
	return domain.JobRecord{JobID: "test-job", JobType: "forecast", Status: "queued", Stage: "queued", CreatedAt: now, UpdatedAt: now}, nil
}
func (f *fake) ForecastDetails(context.Context, string) (domain.ForecastRunDetails, error) {
	return domain.ForecastRunDetails{}, nil
}
func (f *fake) ForecastResult(context.Context, string) (domain.ForecastResult, error) {
	return domain.ForecastResult{}, nil
}
func (f *fake) ListForecasts(context.Context, domain.ListFilter) (domain.ForecastList, error) {
	return domain.ForecastList{}, nil
}
func (f *fake) Explanation(context.Context, string) (domain.ExplanationDetails, error) {
	return domain.ExplanationDetails{}, nil
}
func (f *fake) Weather(context.Context, string) (domain.WeatherDetails, error) {
	return domain.WeatherDetails{}, nil
}
func TestUseCasePolicyAndNormalization(t *testing.T) {
	f := &fake{}
	s, e := NewForecastService(f, f, f, f, true)
	if e != nil {
		t.Fatal(e)
	}
	q := domain.ForecastRequest{ForecastOrigin: time.Date(2026, 1, 31, 23, 0, 0, 0, time.FixedZone("offset", 5*3600)), HorizonHours: 24, TurbineIDs: []int{2, 1}, ModelVersion: "fixture-not-trained", Mode: "replay", DataMode: "fixture"}
	if _, e = s.Create(context.Background(), q, domain.Operation{IdempotencyKey: "key"}); e != nil {
		t.Fatal(e)
	}
	if f.calls != 1 || f.request.TurbineIDs[0] != 1 || f.request.ForecastOrigin.Location() != time.UTC {
		t.Fatal("not normalized")
	}
	s.allowFixtures = false
	if _, e = s.Create(context.Background(), q, domain.Operation{IdempotencyKey: "key2"}); e == nil || f.calls != 1 {
		t.Fatal("fixture policy bypass")
	}
	if _, e = NewForecastService(nil, f, f, f, true); e == nil {
		t.Fatal("nil dependency")
	}
}
