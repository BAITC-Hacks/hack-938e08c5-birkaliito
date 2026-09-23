package agentmock

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"math"
	"time"
	"wind/backend/internal/domain"
)

func (a *Adapter) worker() {
	defer a.wg.Done()
	for {
		select {
		case <-a.ctx.Done():
			return
		case id := <-a.queue:
			a.execute(id)
		}
	}
}
func (a *Adapter) execute(id string) {
	a.mu.Lock()
	r := a.jobs[id]
	if r == nil || domain.Terminal(r.job.Status) || a.closed {
		a.mu.Unlock()
		return
	}
	ctx, cancel := context.WithCancel(a.ctx)
	r.cancel = cancel
	r.job.Status = "running"
	a.event(r, "started", "weather_fetch", "Starting simulated weather retrieval")
	q := clone(r.request)
	created := r.job.CreatedAt
	if r.parent != "" {
		a.updateParent(a.jobs[r.parent])
	}
	a.mu.Unlock()
	defer cancel()
	delay := a.cfg.StepDelay
	if a.cfg.Scenario == "slow" {
		delay *= 100
	}
	err := a.clock.Wait(ctx, delay)
	if err == nil {
		a.mu.Lock()
		a.event(r, "tool_completed", "weather_fetch", "Synthetic weather artifact prepared")
		if a.cfg.Scenario == "degraded" {
			a.event(r, "warning", "recovery", "Simulated source failure; allowed fixture recovery selected")
		}
		a.event(r, "tool_requested", "forecast", "Running deterministic fixture generator")
		a.mu.Unlock()
		err = a.clock.Wait(ctx, delay)
	}
	result, weather := fixture(q, id, created)
	if a.cfg.Scenario == "degraded" {
		result.QualityStatus = "degraded"
		result.Warnings = append(result.Warnings, "MOCK: Simulated weather recovery")
	}
	if a.cfg.Scenario == "llm_unavailable" {
		result.ExplanationStatus = "unavailable"
		result.Explanation = ""
		result.Warnings = append(result.Warnings, "MOCK: LLM unavailable; numerical fixture remains available")
	}
	if a.cfg.Scenario == "weather_future" {
		result.WeatherRuns[0].EffectiveAvailableAt = q.ForecastOrigin.Add(time.Hour)
	}
	validation := domain.ValidateResult(result, q, id)
	a.mu.Lock()
	defer a.mu.Unlock()
	r.cancel = nil
	if r.cancelRequested || err != nil {
		r.job.Status = "cancelled"
		a.event(r, "warning", "cancelled", "Execution cancelled")
	} else if a.cfg.Scenario == "failure" {
		r.job.Status = "failed"
		code, msg := "MOCK_TOOL_FAILED", "MOCK: Controlled fixture tool failure"
		r.job.ErrorCode = &code
		r.job.ErrorMessage = &msg
		a.event(r, "failed", "failed", "Controlled fixture tool failure")
	} else if validation != nil {
		r.job.Status = "failed"
		code, msg := "WEATHER_POLICY_REJECTED", "MOCK: Historical weather availability policy rejected result"
		r.job.ErrorCode = &code
		r.job.ErrorMessage = &msg
		a.event(r, "policy_rejected", "validation", "Weather availability exceeds forecast origin")
		a.event(r, "failed", "failed", "Publication prohibited")
	} else {
		r.result = &result
		r.weather = &weather
		r.job.Status = "completed"
		a.event(r, "completed", "completed", "Validated fixture result published")
	}
	if r.parent != "" {
		a.updateParent(a.jobs[r.parent])
	}
}
func fixture(q domain.ForecastRequest, id string, created time.Time) (domain.ForecastResult, domain.WeatherDetails) {
	r := domain.ForecastResult{RunID: id, ForecastOrigin: q.ForecastOrigin, HorizonHours: q.HorizonHours, TurbineIDs: q.TurbineIDs, DataMode: "fixture", ModelVersion: "fixture-not-trained", FeatureVersion: "fixture-features-v1", TrainingDataAvailableThrough: q.ForecastOrigin.Add(-24 * time.Hour), QualityStatus: "passed", ExplanationStatus: "template", Explanation: "MOCK: Synthetic development fixture, not a trained model or retrieved GFS forecast.", Warnings: []string{"MOCK: Synthetic data — development fixture; no accuracy claim"}, Points: []domain.ForecastPoint{}, WeatherRuns: []domain.WeatherProvenance{}}
	w := domain.WeatherDetails{RunID: id, DataMode: "fixture", Status: "available", WeatherRuns: []domain.WeatherProvenance{}, Points: []domain.WeatherPoint{}}
	for _, t := range q.TurbineIDs {
		for h := 1; h <= q.HorizonHours; h++ {
			valid := q.ForecastOrigin.Add(time.Duration(h) * time.Hour)
			phase := float64(q.ForecastOrigin.Unix()/3600+int64(h))/7 + float64(t)
			mean := 0.48 + 0.3*math.Sin(phase)
			median := mean - 0.01
			r.Points = append(r.Points, domain.ForecastPoint{TurbineID: t, ValidTime: valid, IntervalEnd: valid.Add(time.Hour), LeadHours: h, PowerMean: mean, Q10: mean - 0.14, Q50: &median, Q90: mean + 0.16})
			wind, height, temp := 7+2*math.Sin(phase), 100.0, 5+3*math.Cos(phase)
			w.Points = append(w.Points, domain.WeatherPoint{TurbineID: t, ValidTime: valid, WindSpeedMS: &wind, WindHeightM: &height, TemperatureC: &temp, IsInterpolated: false})
		}
	}
	// Exact artifact bytes are canonical JSON of the weather points returned by /weather.
	artifact := make([]map[string]any, 0, len(w.Points))
	for _, p := range w.Points {
		artifact = append(artifact, map[string]any{"turbine_id": p.TurbineID, "valid_time": p.ValidTime, "wind_speed_ms": p.WindSpeedMS, "wind_height_m": p.WindHeightM, "temperature_c": p.TemperatureC, "is_interpolated": p.IsInterpolated})
	}
	b, _ := json.Marshal(artifact)
	sum := sha256.Sum256(b)
	policy := "fixture-availability-v1"
	provenance := domain.WeatherProvenance{Provider: "GFS", RunID: "fixture-weather-" + hex.EncodeToString(sum[:8]), InitializationTime: q.ForecastOrigin.Add(-6 * time.Hour), EffectiveAvailableAt: q.ForecastOrigin.Add(-3 * time.Hour), AvailabilityBasis: "conservative_policy", AvailabilityPolicyID: &policy, RetrievedAt: created, SourceReference: "fixture://weather/" + hex.EncodeToString(sum[:]), ContentSHA256: hex.EncodeToString(sum[:])}
	r.WeatherRuns = append(r.WeatherRuns, provenance)
	w.WeatherRuns = append(w.WeatherRuns, provenance)
	return r, w
}
