package domain

import (
	"fmt"
	"math"
	"regexp"
	"slices"
	"strings"
	"time"
)

func ValidID(id string) bool {
	ok, _ := regexp.MatchString(`^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$`, id)
	return ok
}
func Terminal(s string) bool    { return s == "completed" || s == "failed" || s == "cancelled" }
func ValidStatus(s string) bool { return s == "queued" || s == "running" || Terminal(s) }
func NormalizeRequest(r ForecastRequest) (ForecastRequest, error) {
	r.ForecastOrigin = r.ForecastOrigin.UTC()
	r.TurbineIDs = slices.Clone(r.TurbineIDs)
	slices.Sort(r.TurbineIDs)
	if r.ForecastOrigin.IsZero() || r.ForecastOrigin.Minute() != 0 || r.ForecastOrigin.Second() != 0 || r.ForecastOrigin.Nanosecond() != 0 {
		return r, Invalid("forecast_origin must be a whole hour in UTC")
	}
	if r.HorizonHours != 24 && r.HorizonHours != 48 {
		return r, Invalid("horizon_hours must be 24 or 48")
	}
	if len(r.TurbineIDs) < 1 || len(r.TurbineIDs) > 2 {
		return r, Invalid("select one or two turbines")
	}
	for i, id := range r.TurbineIDs {
		if (id != 1 && id != 2) || (i > 0 && id == r.TurbineIDs[i-1]) {
			return r, Invalid("turbine_ids must contain unique IDs 1 and/or 2")
		}
	}
	if strings.TrimSpace(r.ModelVersion) == "" || len(r.ModelVersion) > 128 {
		return r, Invalid("model_version must be non-empty, at most 128 bytes")
	}
	if r.Mode != "replay" && r.Mode != "live" {
		return r, Invalid("invalid mode")
	}
	if r.DataMode != "real" && r.DataMode != "fixture" {
		return r, Invalid("invalid data_mode")
	}
	return r, nil
}
func NormalizeReplay(r ReplayRequest) (ReplayRequest, error) {
	if len(r.Origins) < 1 || len(r.Origins) > 366 {
		return r, Invalid("origins must contain 1..366 unique hours")
	}
	r.Origins = slices.Clone(r.Origins)
	seen := map[time.Time]bool{}
	for i, t := range r.Origins {
		q, err := NormalizeRequest(ForecastRequest{ForecastOrigin: t, HorizonHours: r.HorizonHours, TurbineIDs: r.TurbineIDs, ModelVersion: r.ModelVersion, Mode: "replay", DataMode: r.DataMode})
		if err != nil {
			return r, err
		}
		if seen[q.ForecastOrigin] {
			return r, Invalid("duplicate origins after UTC normalization")
		}
		seen[q.ForecastOrigin] = true
		r.Origins[i] = q.ForecastOrigin
		r.TurbineIDs = q.TurbineIDs
	}
	return r, nil
}
func ValidateKey(key string) error {
	if len(key) < 1 || len(key) > 128 {
		return Invalid("Idempotency-Key must contain 1..128 visible ASCII characters")
	}
	for _, c := range key {
		if c < 33 || c > 126 {
			return Invalid("invalid Idempotency-Key")
		}
	}
	return nil
}
func ValidateJob(j JobRecord) error {
	if !ValidID(j.JobID) || !ValidStatus(j.Status) || (j.JobType != "forecast" && j.JobType != "replay") || j.CreatedAt.IsZero() || j.UpdatedAt.Before(j.CreatedAt) || j.Stage == "" {
		return Violation("invalid job metadata")
	}
	if j.Status == "failed" && (j.ErrorCode == nil || j.ErrorMessage == nil) {
		return Violation("failed job must include safe error metadata")
	}
	return nil
}
func ValidateResult(r ForecastResult, req ForecastRequest, id string) error {
	fail := func() error {
		return Violation("forecast violates time, provenance, completeness or request invariants")
	}
	normalized, err := NormalizeRequest(req)
	if err != nil {
		return fail()
	}
	req = normalized
	ids := slices.Clone(r.TurbineIDs)
	slices.Sort(ids)
	if r.RunID != id || !r.ForecastOrigin.Equal(req.ForecastOrigin) || r.HorizonHours != req.HorizonHours || !slices.Equal(ids, req.TurbineIDs) || r.ModelVersion != req.ModelVersion || r.DataMode != req.DataMode {
		return fail()
	}
	if r.FeatureVersion == "" || r.TrainingDataAvailableThrough.IsZero() || r.TrainingDataAvailableThrough.After(r.ForecastOrigin) || len(r.WeatherRuns) == 0 {
		return fail()
	}
	if r.QualityStatus != "passed" && r.QualityStatus != "degraded" {
		return fail()
	}
	if r.ExplanationStatus != "llm" && r.ExplanationStatus != "template" && r.ExplanationStatus != "unavailable" {
		return fail()
	}
	if err := ValidateProvenance(r.WeatherRuns, r.ForecastOrigin, r.DataMode); err != nil {
		return err
	}
	if r.DataMode == "real" && (strings.Contains(r.ModelVersion, "fixture") || strings.Contains(r.FeatureVersion, "fixture")) {
		return fail()
	}
	if r.DataMode == "fixture" && (r.ModelVersion != "fixture-not-trained" || !strings.HasPrefix(r.FeatureVersion, "fixture") || len(r.Warnings) == 0) {
		return fail()
	}
	if len(r.Points) != len(req.TurbineIDs)*req.HorizonHours {
		return fail()
	}
	seen := map[[2]int]bool{}
	for _, p := range r.Points {
		key := [2]int{p.TurbineID, p.LeadHours}
		if seen[key] || !slices.Contains(req.TurbineIDs, p.TurbineID) || p.LeadHours < 1 || p.LeadHours > req.HorizonHours {
			return fail()
		}
		seen[key] = true
		if !p.ValidTime.Equal(req.ForecastOrigin.Add(time.Duration(p.LeadHours)*time.Hour)) || !p.IntervalEnd.Equal(p.ValidTime.Add(time.Hour)) {
			return fail()
		}
		for _, n := range []float64{p.PowerMean, p.Q10, p.Q50, p.Q90} {
			if math.IsNaN(n) || math.IsInf(n, 0) {
				return fail()
			}
		}
		if p.Q10 > p.Q50 || p.Q50 > p.Q90 {
			return fail()
		}
	}
	return nil
}
func ValidateProvenance(runs []WeatherProvenance, origin time.Time, dataMode string) error {
	fail := func() error { return Violation("Invalid weather provenance or historical availability") }
	for _, w := range runs {
		hashOK, _ := regexp.MatchString(`^[a-f0-9]{64}$`, w.ContentSHA256)
		if w.Provider != "GFS" || w.RunID == "" || w.SourceReference == "" || !hashOK || w.InitializationTime.IsZero() || w.EffectiveAvailableAt.IsZero() || w.RetrievedAt.IsZero() || w.InitializationTime.After(w.EffectiveAvailableAt) || w.EffectiveAvailableAt.After(origin) {
			return fail()
		}
		if w.AvailabilityBasis != "observed_publication" && w.AvailabilityBasis != "conservative_policy" {
			return fail()
		}
		if w.AvailabilityBasis == "conservative_policy" && (w.AvailabilityPolicyID == nil || strings.TrimSpace(*w.AvailabilityPolicyID) == "") {
			return fail()
		}
		if dataMode == "real" && (strings.Contains(strings.ToLower(w.SourceReference), "fixture") || strings.HasPrefix(w.RunID, "fixture")) {
			return fail()
		}
	}
	return nil
}
func ValidateWeather(w WeatherDetails, q ForecastRequest, id string) error {
	if w.RunID != id || w.DataMode != q.DataMode {
		return Violation("Wrong weather identity or data mode")
	}
	if w.Status == "unavailable" {
		if len(w.Points) > 0 {
			return Violation("Unavailable weather cannot contain points")
		}
		return nil
	}
	if w.Status != "available" || len(w.WeatherRuns) == 0 {
		return Violation("Missing weather provenance")
	}
	if e := ValidateProvenance(w.WeatherRuns, q.ForecastOrigin, q.DataMode); e != nil {
		return e
	}
	seen := map[[2]int64]bool{}
	for _, p := range w.Points {
		gap := p.ValidTime.Sub(q.ForecastOrigin)
		if !slices.Contains(q.TurbineIDs, p.TurbineID) || gap < time.Hour || gap > time.Duration(q.HorizonHours)*time.Hour || gap%time.Hour != 0 {
			return Violation("Weather point outside forecast request")
		}
		key := [2]int64{int64(p.TurbineID), int64(gap / time.Hour)}
		if seen[key] {
			return Violation("Repeated weather point")
		}
		seen[key] = true
		for _, n := range []*float64{p.WindSpeedMS, p.WindHeightM, p.TemperatureC} {
			if n != nil && (math.IsNaN(*n) || math.IsInf(*n, 0)) {
				return Violation("Nonfinite weather point")
			}
		}
	}
	return nil
}
func ValidateEvents(events []AgentEvent, id string, after int64) error {
	for _, e := range events {
		if e.JobID != id || e.EventID <= after || e.EventID > 9007199254740991 || e.RecordedAt.IsZero() {
			return Violation("invalid event ordering or identity")
		}
		after = e.EventID
	}
	return nil
}

type ListFilter struct {
	From, To                 *time.Time
	TurbineID                int
	Status, DataMode, Cursor string
	Limit                    int
}

func (f ListFilter) Validate() error {
	if f.Limit < 1 || f.Limit > 100 {
		return Invalid("limit must be 1..100")
	}
	if f.From != nil && f.To != nil && !f.From.Before(*f.To) {
		return Invalid("origin range must have from < to")
	}
	if f.TurbineID != 0 && f.TurbineID != 1 && f.TurbineID != 2 {
		return Invalid("invalid turbine_id")
	}
	if f.Status != "" && !ValidStatus(f.Status) {
		return Invalid("invalid status")
	}
	if f.DataMode != "" && f.DataMode != "real" && f.DataMode != "fixture" {
		return Invalid("invalid data_mode")
	}
	return nil
}
func (f ListFilter) FilterKey() string {
	return fmt.Sprintf("%v|%v|%d|%s|%s|%d", f.From, f.To, f.TurbineID, f.Status, f.DataMode, f.Limit)
}

type Operation struct{ RequestID, IdempotencyKey string }
type Export struct {
	Results  []ForecastResult
	Counters ReplayCounters
	Partial  bool
}
