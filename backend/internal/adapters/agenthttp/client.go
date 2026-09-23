// Package agenthttp implements the proposed /internal/v1 Python protocol.
// Python owns real jobs; this adapter has no job store or fixture fallback.
package agenthttp

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"mime"
	"net"
	"net/http"
	"net/url"
	"strconv"
	"strings"
	"time"
	"wind/backend/api"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/domain"
)

type Config struct {
	BaseURL, Token string
	Timeout        time.Duration
	ResponseLimit  int64
}
type Adapter struct {
	cfg       Config
	client    *http.Client
	validator *api.Validator
	transport *http.Transport
}

func New(cfg Config, v *api.Validator) (*Adapter, error) {
	u, e := url.Parse(cfg.BaseURL)
	if e != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, fmt.Errorf("invalid Python base URL")
	}
	if cfg.Timeout <= 0 || cfg.ResponseLimit <= 0 || v == nil {
		return nil, fmt.Errorf("invalid upstream configuration")
	}
	t := &http.Transport{Proxy: http.ProxyFromEnvironment, DialContext: (&net.Dialer{Timeout: cfg.Timeout, KeepAlive: 30 * time.Second}).DialContext, MaxIdleConns: 32, MaxIdleConnsPerHost: 16, MaxConnsPerHost: 32, IdleConnTimeout: 90 * time.Second, TLSHandshakeTimeout: cfg.Timeout, ResponseHeaderTimeout: cfg.Timeout}
	c := &http.Client{Transport: t, Timeout: cfg.Timeout, CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	cfg.BaseURL = strings.TrimRight(cfg.BaseURL, "/")
	return &Adapter{cfg, c, v, t}, nil
}
func (a *Adapter) Close() { a.transport.CloseIdleConnections() }
func (a *Adapter) request(ctx context.Context, method, path, schema string, body any, op domain.Operation, statuses ...int) ([]byte, error) {
	ctx, cancel := context.WithTimeout(ctx, a.cfg.Timeout)
	defer cancel()
	var data []byte
	var e error
	if body != nil {
		data, e = json.Marshal(body)
		if e != nil {
			return nil, domain.Violation("Cannot encode upstream request")
		}
	}
	attempts := 1
	if method == "GET" {
		attempts = 2
	}
	for attempt := 0; attempt < attempts; attempt++ {
		if attempt > 0 {
			timer := time.NewTimer(25 * time.Millisecond)
			select {
			case <-ctx.Done():
				timer.Stop()
				return nil, domain.Wrap("UPSTREAM_TIMEOUT", "Python request deadline exceeded", ctx.Err())
			case <-timer.C:
			}
		}
		b, err := a.once(ctx, method, path, data, op, statuses)
		if err != nil {
			var de *domain.Error
			if attempt+1 < attempts && errors.As(err, &de) && de.Code == "DEPENDENCY_UNAVAILABLE" {
				continue
			}
			return nil, err
		}
		if schema != "" {
			if err = a.validator.Validate(schema, b); err != nil {
				return nil, domain.Wrap("UPSTREAM_CONTRACT_VIOLATION", "Python JSON does not match the agreed schema", err)
			}
		}
		return b, nil
	}
	return nil, domain.Err("DEPENDENCY_UNAVAILABLE", "Python unavailable")
}
func (a *Adapter) once(ctx context.Context, method, path string, data []byte, op domain.Operation, statuses []int) ([]byte, error) {
	req, e := http.NewRequestWithContext(ctx, method, a.cfg.BaseURL+"/internal/v1"+path, bytes.NewReader(data))
	if e != nil {
		return nil, domain.Wrap("DEPENDENCY_UNAVAILABLE", "Cannot contact Python", e)
	}
	req.Header.Set("Accept", "application/json")
	if method == "POST" {
		req.Header.Set("Content-Type", "application/json")
	}
	if op.IdempotencyKey != "" {
		req.Header.Set("Idempotency-Key", op.IdempotencyKey)
	}
	rid := op.RequestID
	if rid == "" {
		rid = ports.RequestID(ctx)
	}
	if rid != "" {
		req.Header.Set("X-Request-ID", rid)
	}
	if a.cfg.Token != "" {
		req.Header.Set("Authorization", "Bearer "+a.cfg.Token)
	}
	resp, e := a.client.Do(req)
	if e != nil {
		var ne net.Error
		if errors.Is(e, context.DeadlineExceeded) || errors.As(e, &ne) && ne.Timeout() {
			return nil, domain.Wrap("UPSTREAM_TIMEOUT", "Python request timed out; retry creation using the same idempotency key", e)
		}
		return nil, domain.Wrap("DEPENDENCY_UNAVAILABLE", "Python dependency unavailable", e)
	}
	defer resp.Body.Close()
	b, e := io.ReadAll(io.LimitReader(resp.Body, a.cfg.ResponseLimit+1))
	if e != nil {
		return nil, domain.Wrap("DEPENDENCY_UNAVAILABLE", "Python response interrupted", e)
	}
	if int64(len(b)) > a.cfg.ResponseLimit {
		return nil, domain.Violation("Python response exceeds configured limit")
	}
	accepted := false
	for _, s := range statuses {
		if resp.StatusCode == s {
			accepted = true
		}
	}
	if !accepted {
		return nil, a.statusError(resp.StatusCode, b)
	}
	content, _, e := mime.ParseMediaType(resp.Header.Get("Content-Type"))
	if e != nil || content != "application/json" || !json.Valid(b) {
		return nil, domain.Violation("Python returned malformed JSON or unexpected Content-Type")
	}
	return b, nil
}
func (a *Adapter) statusError(status int, b []byte) error {
	switch status {
	case 404:
		return domain.Err("NOT_FOUND", "Upstream resource not found")
	case 422:
		return domain.Invalid("Python rejected request parameters")
	case 501:
		return domain.Err("FEATURE_NOT_SUPPORTED", "Python capability is not implemented")
	case 429:
		return domain.Err("RATE_LIMITED", "Python rate limit reached")
	case 504:
		return domain.Err("UPSTREAM_TIMEOUT", "Python timed out")
	case 500, 502, 503:
		return domain.Err("DEPENDENCY_UNAVAILABLE", "Python dependency temporarily unavailable")
	case 410:
		return domain.Err("EVENT_CURSOR_EXPIRED", "Upstream event cursor expired")
	case 400:
		return domain.Err("INVALID_CURSOR", "Python rejected cursor or query")
	case 409:
		var e ApiError
		if a.validator.Validate("ApiError", b) == nil && json.Unmarshal(b, &e) == nil {
			switch e.Code {
			case "IDEMPOTENCY_CONFLICT", "RESULT_NOT_READY", "JOB_NOT_CANCELLABLE", "REPLAY_INCOMPLETE":
				return domain.Err(e.Code, "Python reported a state or idempotency conflict")
			}
		}
		return domain.Violation("Python returned an unrecognized conflict")
	default:
		return domain.Violation("Unexpected Python HTTP status")
	}
}
func decode[T any](b []byte) (T, error) {
	var v T
	if e := json.Unmarshal(b, &v); e != nil {
		return v, domain.Wrap("UPSTREAM_CONTRACT_VIOLATION", "Python response cannot be decoded", e)
	}
	return v, nil
}
func get[T any](a *Adapter, ctx context.Context, path, schema string) (T, error) {
	b, e := a.request(ctx, "GET", path, schema, nil, domain.Operation{}, 200)
	if e != nil {
		var z T
		return z, e
	}
	return decode[T](b)
}
func (a *Adapter) Ready(ctx context.Context) error {
	_, e := get[Health](a, ctx, "/readyz", "Health")
	return e
}
func (a *Adapter) Capabilities(ctx context.Context) (domain.Capabilities, error) {
	v, e := get[Meta](a, ctx, "/meta", "Meta")
	if e != nil {
		return domain.Capabilities{}, e
	}
	if v.Capabilities.Simulated || v.AgentMode != "http" {
		return domain.Capabilities{}, domain.Violation("Real dependency cannot announce simulated mode")
	}
	return CapabilitiesToDomain(v.Capabilities), nil
}
func (a *Adapter) Models(ctx context.Context) (domain.ModelList, error) {
	v, e := get[ModelList](a, ctx, "/models", "ModelList")
	if e != nil {
		return domain.ModelList{}, e
	}
	for _, m := range v.Items {
		if m.DataMode != "real" || strings.Contains(m.ModelVersion, "fixture") || m.TrainingDataAvailableThrough.IsZero() {
			return domain.ModelList{}, domain.Violation("Real model catalog contains fixtures")
		}
	}
	return ModelListToDomain(v), nil
}
func (a *Adapter) CreateForecast(ctx context.Context, q domain.ForecastRequest, op domain.Operation) (domain.JobRecord, error) {
	if q.DataMode != "real" {
		return domain.JobRecord{}, domain.Err("DATA_MODE_MISMATCH", "HTTP adapter accepts real data only")
	}
	b, e := a.request(ctx, "POST", "/forecast-runs", "JobRecord", ForecastRequestFromDomain(q), op, 202)
	if e != nil {
		return domain.JobRecord{}, e
	}
	v, e := decode[JobRecord](b)
	if e != nil {
		return domain.JobRecord{}, e
	}
	j := JobRecordToDomain(v)
	if e = domain.ValidateJob(j); e != nil {
		return j, e
	}
	if j.JobType != "forecast" {
		return j, domain.Violation("Wrong created job type")
	}
	return j, nil
}
func (a *Adapter) GetJob(ctx context.Context, id string) (domain.JobRecord, error) {
	v, e := get[JobRecord](a, ctx, "/jobs/"+url.PathEscape(id), "JobRecord")
	if e != nil {
		return domain.JobRecord{}, e
	}
	j := JobRecordToDomain(v)
	if j.JobID != id {
		return j, domain.Violation("Wrong job id")
	}
	return j, domain.ValidateJob(j)
}
func (a *Adapter) ForecastDetails(ctx context.Context, id string) (domain.ForecastRunDetails, error) {
	v, e := get[ForecastRunDetails](a, ctx, "/forecast-runs/"+url.PathEscape(id), "ForecastRunDetails")
	if e != nil {
		return domain.ForecastRunDetails{}, e
	}
	d := ForecastRunDetailsToDomain(v)
	if d.Job.JobID != id || d.Job.JobType != "forecast" || d.Request.DataMode != "real" {
		return d, domain.Violation("Wrong forecast identity or data mode")
	}
	if _, e = domain.NormalizeRequest(d.Request); e != nil {
		return d, domain.Violation("Invalid upstream forecast request")
	}
	if d.ResultAvailable != (d.Job.Status == "completed") {
		return d, domain.Violation("Result availability disagrees with job state")
	}
	return d, domain.ValidateJob(d.Job)
}
func (a *Adapter) ForecastResult(ctx context.Context, id string) (domain.ForecastResult, error) {
	d, e := a.ForecastDetails(ctx, id)
	if e != nil {
		return domain.ForecastResult{}, e
	}
	v, e := get[ForecastResult](a, ctx, "/forecast-runs/"+url.PathEscape(id)+"/result", "ForecastResult")
	if e != nil {
		return domain.ForecastResult{}, e
	}
	r := ForecastResultToDomain(v)
	return r, domain.ValidateResult(r, d.Request, id)
}
func (a *Adapter) Events(ctx context.Context, id string, after int64, limit int) ([]domain.AgentEvent, error) {
	b, e := a.request(ctx, "GET", "/jobs/"+url.PathEscape(id)+"/events?after="+strconv.FormatInt(after, 10)+"&limit="+strconv.Itoa(limit), "", nil, domain.Operation{}, 200)
	if e != nil {
		return nil, e
	}
	var raw []json.RawMessage
	if e = json.Unmarshal(b, &raw); e != nil || raw == nil || len(raw) > limit {
		return nil, domain.Violation("Expected bounded event array")
	}
	out := make([]domain.AgentEvent, 0, len(raw))
	for _, b := range raw {
		if e = a.validator.Validate("AgentEvent", b); e != nil {
			return nil, domain.Violation("Invalid agent event")
		}
		v, e := decode[AgentEvent](b)
		if e != nil {
			return nil, e
		}
		if strings.HasPrefix(v.Message, "MOCK:") {
			return nil, domain.Violation("Fixture event in real mode")
		}
		out = append(out, AgentEventToDomain(v))
	}
	return out, domain.ValidateEvents(out, id, after)
}
func (a *Adapter) Cancel(ctx context.Context, id string) (domain.JobRecord, error) {
	b, e := a.request(ctx, "POST", "/jobs/"+url.PathEscape(id)+"/cancel", "JobRecord", nil, domain.Operation{}, 200, 202)
	if e != nil {
		return domain.JobRecord{}, e
	}
	v, e := decode[JobRecord](b)
	if e != nil {
		return domain.JobRecord{}, e
	}
	j := JobRecordToDomain(v)
	if j.JobID != id || j.Status == "completed" || j.Status == "failed" {
		return j, domain.Violation("Invalid cancellation response")
	}
	return j, domain.ValidateJob(j)
}
func query(f domain.ListFilter) string {
	v := url.Values{}
	v.Set("limit", strconv.Itoa(f.Limit))
	if f.Cursor != "" {
		v.Set("cursor", f.Cursor)
	}
	if f.Status != "" {
		v.Set("status", f.Status)
	}
	if f.DataMode != "" {
		v.Set("data_mode", f.DataMode)
	}
	if f.TurbineID != 0 {
		v.Set("turbine_id", strconv.Itoa(f.TurbineID))
	}
	if f.From != nil {
		v.Set("forecast_origin_from", f.From.UTC().Format(time.RFC3339Nano))
	}
	if f.To != nil {
		v.Set("forecast_origin_to", f.To.UTC().Format(time.RFC3339Nano))
	}
	return "?" + v.Encode()
}
func (a *Adapter) ListForecasts(ctx context.Context, f domain.ListFilter) (domain.ForecastList, error) {
	v, e := get[ForecastList](a, ctx, "/forecast-runs"+query(f), "ForecastList")
	if e != nil {
		return domain.ForecastList{}, e
	}
	for _, d := range v.Items {
		if d.Request.DataMode != "real" || d.Job.JobType != "forecast" {
			return domain.ForecastList{}, domain.Violation("Invalid real forecast list")
		}
		if e = domain.ValidateJob(JobRecordToDomain(d.Job)); e != nil {
			return domain.ForecastList{}, e
		}
	}
	return ForecastListToDomain(v), nil
}
func (a *Adapter) CreateReplay(ctx context.Context, q domain.ReplayRequest, op domain.Operation) (domain.JobRecord, error) {
	if q.DataMode != "real" {
		return domain.JobRecord{}, domain.Err("DATA_MODE_MISMATCH", "HTTP accepts real only")
	}
	b, e := a.request(ctx, "POST", "/replays", "JobRecord", ReplayRequestFromDomain(q), op, 202)
	if e != nil {
		return domain.JobRecord{}, e
	}
	v, e := decode[JobRecord](b)
	if e != nil {
		return domain.JobRecord{}, e
	}
	j := JobRecordToDomain(v)
	if j.JobType != "replay" {
		return j, domain.Violation("Wrong replay job type")
	}
	return j, domain.ValidateJob(j)
}
func (a *Adapter) ReplayDetails(ctx context.Context, id string) (domain.ReplayDetails, error) {
	v, e := get[ReplayDetails](a, ctx, "/replays/"+url.PathEscape(id), "ReplayDetails")
	if e != nil {
		return domain.ReplayDetails{}, e
	}
	d := ReplayDetailsToDomain(v)
	if _,e=domain.NormalizeReplay(d.Request);e!=nil{return d,domain.Violation("Invalid replay request metadata")}
	c := d.Counters
	if d.Job.JobID != id || d.Job.JobType != "replay" || d.Request.DataMode != "real" || c.Total != len(d.Request.Origins) || c.Total != c.Queued+c.Running+c.Completed+c.Failed+c.Cancelled || d.HasFailures != (c.Failed > 0) {
		return d, domain.Violation("Invalid replay metadata or counters")
	}
	if domain.Terminal(d.Job.Status) && (c.Queued+c.Running != 0 || d.Job.Status == "completed" && c.Completed != c.Total) {
		return d, domain.Violation("Replay status contradicts counters")
	}
	return d, domain.ValidateJob(d.Job)
}
func (a *Adapter) ReplayRuns(ctx context.Context, id string) ([]domain.JobRecord, error) {
	b, e := a.request(ctx, "GET", "/replays/"+url.PathEscape(id)+"/runs", "", nil, domain.Operation{}, 200)
	if e != nil {
		return nil, e
	}
	var raw []json.RawMessage
	if e = json.Unmarshal(b, &raw); e != nil || raw == nil {
		return nil, domain.Violation("Expected replay children array")
	}
	out := make([]domain.JobRecord, 0, len(raw))
	seen := map[string]bool{}
	for _, b := range raw {
		if a.validator.Validate("JobRecord", b) != nil {
			return nil, domain.Violation("Invalid replay child")
		}
		v, e := decode[JobRecord](b)
		if e != nil {
			return nil, e
		}
		j := JobRecordToDomain(v)
		if j.JobType != "forecast" || seen[j.JobID] {
			return nil, domain.Violation("Invalid or repeated child job")
		}
		seen[j.JobID] = true
		if e = domain.ValidateJob(j); e != nil {
			return nil, e
		}
		out = append(out, j)
	}
	return out, nil
}
func (a *Adapter) Weather(ctx context.Context, id string) (domain.WeatherDetails, error) {
	v, e := get[WeatherDetails](a, ctx, "/forecast-runs/"+url.PathEscape(id)+"/weather", "WeatherDetails")
	if e != nil {
		return domain.WeatherDetails{}, e
	}
	if v.RunID != id || v.DataMode != "real" {
		return domain.WeatherDetails{}, domain.Violation("Wrong weather identity or data mode")
	}
	for _, w := range v.WeatherRuns {
		if strings.Contains(w.SourceReference, "fixture") {
			return domain.WeatherDetails{}, domain.Violation("Fixture weather in real mode")
		}
	}
	return WeatherDetailsToDomain(v), nil
}
func (a *Adapter) Explanation(ctx context.Context, id string) (domain.ExplanationDetails, error) {
	v, e := get[ExplanationDetails](a, ctx, "/forecast-runs/"+url.PathEscape(id)+"/explanation", "ExplanationDetails")
	if e != nil {
		return domain.ExplanationDetails{}, e
	}
	if v.RunID != id || v.DataMode != "real" {
		return domain.ExplanationDetails{}, domain.Violation("Wrong explanation identity or data mode")
	}
	if v.SHAPStatus == "unavailable" && len(v.SHAPItems) != 0 {
		return domain.ExplanationDetails{}, domain.Violation("Unavailable SHAP must have no items")
	}
	return ExplanationDetailsToDomain(v), nil
}
func validateEvaluation(r domain.EvaluationReport) error {
	if r.DataMode != "real" || r.PeriodStart.IsZero() || r.PeriodEnd.IsZero() || r.TrainingDataAvailableThrough.IsZero() || !r.PeriodStart.Before(r.PeriodEnd) || r.TrainingDataAvailableThrough.After(r.PeriodStart) {
		return domain.Violation("Invalid evaluation provenance")
	}
	if r.Status=="unavailable"&&r.NObservations!=nil{return domain.Violation("Unavailable observation count must be null")}
	for _, m := range r.Metrics {
		if m.LeadFrom > m.LeadTo {
			return domain.Violation("Invalid metric horizon")
		}
		if r.Status == "unavailable" && (m.MAE != nil || m.RMSE != nil || m.Bias != nil || m.CoverageQ10Q90 != nil || m.MeanIntervalWidth != nil) {
			return domain.Violation("Unavailable metrics must be null")
		}
	}
	return nil
}
func (a *Adapter) Evaluation(ctx context.Context, id string) (domain.EvaluationReport, error) {
	v, e := get[EvaluationReport](a, ctx, "/evaluations/"+url.PathEscape(id), "EvaluationReport")
	if e != nil {
		return domain.EvaluationReport{}, e
	}
	r := EvaluationReportToDomain(v)
	if r.EvaluationID != id {
		return r, domain.Violation("Wrong evaluation id")
	}
	return r, validateEvaluation(r)
}
func (a *Adapter) Evaluations(ctx context.Context, f domain.ListFilter) (domain.EvaluationList, error) {
	v, e := get[EvaluationList](a, ctx, "/evaluations"+query(f), "EvaluationList")
	if e != nil {
		return domain.EvaluationList{}, e
	}
	r := EvaluationListToDomain(v)
	for _, item := range r.Items {
		if e = validateEvaluation(item); e != nil {
			return r, e
		}
	}
	return r, nil
}
func (a *Adapter) DataQuality(ctx context.Context) (domain.DataQualityReport, error) {
	v, e := get[DataQualityReport](a, ctx, "/data-quality", "DataQualityReport")
	if e != nil {
		return domain.DataQualityReport{}, e
	}
	if v.DataMode != "real" || v.SourceReference != nil && strings.Contains(*v.SourceReference, "fixture") {
		return domain.DataQualityReport{}, domain.Violation("Fixture audit in real mode")
	}
	return DataQualityReportToDomain(v), nil
}
