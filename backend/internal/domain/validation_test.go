package domain

import (
	"math"
	"strings"
	"testing"
	"time"
)

func validFixture(h int, ids []int) (ForecastRequest, ForecastResult) {
	origin := time.Date(2026, 1, 31, 18, 0, 0, 0, time.UTC)
	q := ForecastRequest{ForecastOrigin: origin, HorizonHours: h, TurbineIDs: ids, ModelVersion: "fixture-not-trained", Mode: "replay", DataMode: "fixture"}
	policy := "fixture-policy"
	r := ForecastResult{RunID: "fixture-run-1", ForecastOrigin: origin, HorizonHours: h, TurbineIDs: ids, DataMode: "fixture", ModelVersion: q.ModelVersion, FeatureVersion: "fixture-v1", TrainingDataAvailableThrough: origin.Add(-time.Hour), QualityStatus: "passed", ExplanationStatus: "template", Warnings: []string{"MOCK: fixture"}, WeatherRuns: []WeatherProvenance{{Provider: "GFS", RunID: "fixture-weather", InitializationTime: origin.Add(-6 * time.Hour), EffectiveAvailableAt: origin.Add(-3 * time.Hour), AvailabilityBasis: "conservative_policy", AvailabilityPolicyID: &policy, RetrievedAt: time.Now(), SourceReference: "fixture://weather", ContentSHA256: strings.Repeat("a", 64)}}}
	for _, id := range ids {
		for lead := 1; lead <= h; lead++ {
			valid := origin.Add(time.Duration(lead) * time.Hour)
			r.Points = append(r.Points, ForecastPoint{TurbineID: id, LeadHours: lead, ValidTime: valid, IntervalEnd: valid.Add(time.Hour), PowerMean: 2, Q10: -1, Q50: 0, Q90: 1})
		}
	}
	return q, r
}
func TestResultInvariants(t *testing.T) {
	for _, h := range []int{24, 48} {
		for _, ids := range [][]int{{1}, {2}, {1, 2}} {
			q, r := validFixture(h, ids)
			if e := ValidateResult(r, q, r.RunID); e != nil {
				t.Fatal(e)
			}
		}
	}
	cases := map[string]func(*ForecastResult){"missing": func(r *ForecastResult) { r.Points = r.Points[1:] }, "duplicate": func(r *ForecastResult) { r.Points[1] = r.Points[0] }, "time": func(r *ForecastResult) { r.Points[0].ValidTime = r.ForecastOrigin }, "interval": func(r *ForecastResult) { r.Points[0].IntervalEnd = r.Points[0].ValidTime }, "nan": func(r *ForecastResult) { r.Points[0].PowerMean = math.NaN() }, "infinite": func(r *ForecastResult) { r.Points[0].Q90 = math.Inf(1) }, "quantiles": func(r *ForecastResult) { r.Points[0].Q10 = 9 }, "weather": func(r *ForecastResult) { r.WeatherRuns[0].EffectiveAvailableAt = r.ForecastOrigin.Add(time.Hour) }, "training": func(r *ForecastResult) { r.TrainingDataAvailableThrough = r.ForecastOrigin.Add(time.Hour) }, "policy": func(r *ForecastResult) { r.WeatherRuns[0].AvailabilityPolicyID = nil }, "identity": func(r *ForecastResult) { r.RunID = "wrong" }, "mode": func(r *ForecastResult) { r.DataMode = "real" }}
	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			q, r := validFixture(24, []int{1, 2})
			mutate(&r)
			if ValidateResult(r, q, "fixture-run-1") == nil {
				t.Fatal("invalid result accepted")
			}
		})
	}
}
func TestUTCNormalization(t *testing.T) {
	q, _ := validFixture(24, []int{2, 1})
	q.ForecastOrigin = time.Date(2026, 1, 31, 23, 30, 0, 0, time.FixedZone("half", 5*3600+1800))
	r, e := NormalizeRequest(q)
	if e != nil || r.ForecastOrigin.Hour() != 18 || r.TurbineIDs[0] != 1 {
		t.Fatalf("%+v %v", r, e)
	}
	q.ForecastOrigin = q.ForecastOrigin.Add(30 * time.Minute)
	if _, e = NormalizeRequest(q); e == nil {
		t.Fatal("UTC half-hour accepted")
	}
}
