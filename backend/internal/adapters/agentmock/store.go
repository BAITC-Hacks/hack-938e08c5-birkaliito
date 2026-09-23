// Package agentmock owns fixture execution only. It is never a fallback for Python.
package agentmock

import (
	"context"
	"crypto/sha256"
	"encoding/base64"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"slices"
	"sort"
	"sync"
	"time"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/domain"
)

type Config struct {
	Workers, QueueCapacity, MaxJobs, MaxEvents int
	Scenario                                   string
	StepDelay                                  time.Duration
}
type record struct {
	job             domain.JobRecord
	request         domain.ForecastRequest
	replay          domain.ReplayRequest
	parent          string
	children        []string
	cancelRequested bool
	cancel          context.CancelFunc
	events          []domain.AgentEvent
	lastEvent       int64
	result          *domain.ForecastResult
	weather         *domain.WeatherDetails
}
type idem struct{ fingerprint, id string }
type Adapter struct {
	mu     sync.Mutex
	cfg    Config
	clock  ports.Clock
	ctx    context.Context
	stop   context.CancelFunc
	wg     sync.WaitGroup
	queue  chan string
	jobs   map[string]*record
	keys   map[string]idem
	seq    uint64
	closed bool
}

func New(cfg Config, clock ports.Clock) *Adapter {
	ctx, cancel := context.WithCancel(context.Background())
	a := &Adapter{cfg: cfg, clock: clock, ctx: ctx, stop: cancel, queue: make(chan string, cfg.QueueCapacity), jobs: map[string]*record{}, keys: map[string]idem{}}
	for i := 0; i < cfg.Workers; i++ {
		a.wg.Add(1)
		go a.worker()
	}
	return a
}
func (a *Adapter) Close() { a.mu.Lock(); a.closed = true; a.stop(); a.mu.Unlock(); a.wg.Wait() }
func (a *Adapter) Ready(context.Context) error {
	a.mu.Lock()
	defer a.mu.Unlock()
	if a.closed {
		return domain.Err("DEPENDENCY_UNAVAILABLE", "Simulator stopped")
	}
	return nil
}
func (a *Adapter) Capabilities(context.Context) (domain.Capabilities, error) {
	return domain.Capabilities{Forecast: true, Replay: true, Cancel: true, SSE: true, WeatherDetails: true, SHAP: false, Evaluations: true, DataQuality: true, Simulated: true}, nil
}
func clone[T any](v T) T {
	b, e := json.Marshal(v)
	if e != nil {
		panic(e)
	}
	var out T
	if e = json.Unmarshal(b, &out); e != nil {
		panic(e)
	}
	return out
}
func fingerprint(v any) string {
	b, _ := json.Marshal(v)
	h := sha256.Sum256(b)
	return hex.EncodeToString(h[:])
}
func (a *Adapter) accept(endpoint, key, fp string, n int) (*record, error) {
	if a.closed {
		return nil, domain.Err("DEPENDENCY_UNAVAILABLE", "Simulator stopping")
	}
	if entry, ok := a.keys[a.cfg.Scenario+":"+endpoint+":"+key]; ok {
		if entry.fingerprint != fp {
			return nil, domain.Err("IDEMPOTENCY_CONFLICT", "Key already used for a different normalized request")
		}
		return a.jobs[entry.id], nil
	}
	if len(a.jobs)+n > a.cfg.MaxJobs || len(a.queue)+n > cap(a.queue) {
		return nil, domain.Err("QUEUE_FULL", "Fixture queue or job retention limit reached")
	}
	return nil, nil
}
func (a *Adapter) newRecord(kind string) *record {
	a.seq++
	now := a.clock.Now().UTC()
	r := &record{job: domain.JobRecord{JobID: fmt.Sprintf("fixture-%s-%06d", kind, a.seq), JobType: kind, Status: "queued", CreatedAt: now, UpdatedAt: now, Stage: "queued"}, events: []domain.AgentEvent{}, children: []string{}}
	a.jobs[r.job.JobID] = r
	a.event(r, "tool_requested", "queue", "Fixture task accepted")
	return r
}
func (a *Adapter) event(r *record, kind, node, msg string) {
	r.lastEvent++
	r.job.UpdatedAt = a.clock.Now().UTC()
	r.job.Stage = node
	r.events = append(r.events, domain.AgentEvent{EventID: r.lastEvent, JobID: r.job.JobID, RecordedAt: r.job.UpdatedAt, Kind: kind, Node: node, Message: "MOCK: " + msg, EvidenceRefs: []string{}})
	if len(r.events) > a.cfg.MaxEvents {
		r.events = slices.Clone(r.events[len(r.events)-a.cfg.MaxEvents:])
	}
}
func (a *Adapter) CreateForecast(ctx context.Context, q domain.ForecastRequest, op domain.Operation) (domain.JobRecord, error) {
	if e := ctx.Err(); e != nil {
		return domain.JobRecord{}, e
	}
	if q.DataMode != "fixture" {
		return domain.JobRecord{}, domain.Err("DATA_MODE_MISMATCH", "Mock accepts fixture only")
	}
	q, e := domain.NormalizeRequest(q)
	if e != nil {
		return domain.JobRecord{}, e
	}
	fp := fingerprint(q)
	a.mu.Lock()
	defer a.mu.Unlock()
	old, e := a.accept("forecast", op.IdempotencyKey, fp, 1)
	if e != nil {
		return domain.JobRecord{}, e
	}
	if old != nil {
		return clone(old.job), nil
	}
	r := a.newRecord("forecast")
	r.request = clone(q)
	a.keys[a.cfg.Scenario+":forecast:"+op.IdempotencyKey] = idem{fp, r.job.JobID}
	a.queue <- r.job.JobID
	return clone(r.job), nil
}
func (a *Adapter) CreateReplay(ctx context.Context, q domain.ReplayRequest, op domain.Operation) (domain.JobRecord, error) {
	if e := ctx.Err(); e != nil {
		return domain.JobRecord{}, e
	}
	if q.DataMode != "fixture" {
		return domain.JobRecord{}, domain.Err("DATA_MODE_MISMATCH", "Mock accepts fixture only")
	}
	q, e := domain.NormalizeReplay(q)
	if e != nil {
		return domain.JobRecord{}, e
	}
	canonical := clone(q)
	sort.Slice(canonical.Origins, func(i, j int) bool { return canonical.Origins[i].Before(canonical.Origins[j]) })
	fp := fingerprint(canonical)
	a.mu.Lock()
	defer a.mu.Unlock()
	// Reserve parent retention separately; only children occupy execution queue slots.
	old, e := a.accept("replay", op.IdempotencyKey, fp, len(q.Origins))
	if e != nil {
		return domain.JobRecord{}, e
	}
	if old != nil {
		return clone(old.job), nil
	}
	if len(a.jobs)+len(q.Origins)+1 > a.cfg.MaxJobs {
		return domain.JobRecord{}, domain.Err("QUEUE_FULL", "Fixture retention limit reached")
	}
	p := a.newRecord("replay")
	p.replay = clone(q)
	for _, t := range q.Origins {
		r := a.newRecord("forecast")
		r.parent = p.job.JobID
		r.request = domain.ForecastRequest{ForecastOrigin: t, HorizonHours: q.HorizonHours, TurbineIDs: slices.Clone(q.TurbineIDs), ModelVersion: q.ModelVersion, Mode: "replay", DataMode: q.DataMode}
		p.children = append(p.children, r.job.JobID)
		a.queue <- r.job.JobID
	}
	a.keys[a.cfg.Scenario+":replay:"+op.IdempotencyKey] = idem{fp, p.job.JobID}
	return clone(p.job), nil
}
func (a *Adapter) find(id, kind string) (*record, error) {
	r, ok := a.jobs[id]
	if !ok || (kind != "" && r.job.JobType != kind) {
		return nil, domain.Err("NOT_FOUND", "Resource not found")
	}
	return r, nil
}
func (a *Adapter) GetJob(_ context.Context, id string) (domain.JobRecord, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "")
	if e != nil {
		return domain.JobRecord{}, e
	}
	return clone(r.job), nil
}
func (a *Adapter) details(r *record) domain.ForecastRunDetails {
	var parent *string
	if r.parent != "" {
		v := r.parent
		parent = &v
	}
	return domain.ForecastRunDetails{Job: clone(r.job), Request: clone(r.request), ParentReplayID: parent, ResultAvailable: r.result != nil, CancelRequested: r.cancelRequested}
}
func (a *Adapter) ForecastDetails(_ context.Context, id string) (domain.ForecastRunDetails, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "forecast")
	if e != nil {
		return domain.ForecastRunDetails{}, e
	}
	return a.details(r), nil
}
func (a *Adapter) ForecastResult(_ context.Context, id string) (domain.ForecastResult, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "forecast")
	if e != nil {
		return domain.ForecastResult{}, e
	}
	if r.result == nil {
		return domain.ForecastResult{}, domain.Err("RESULT_NOT_READY", "Forecast result is not available yet.")
	}
	return clone(*r.result), nil
}
func (a *Adapter) Events(_ context.Context, id string, after int64, limit int) ([]domain.AgentEvent, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "")
	if e != nil {
		return nil, e
	}
	if after < 0 || after > r.lastEvent {
		return nil, domain.Err("INVALID_CURSOR", "Event cursor exceeds the job log")
	}
	if len(r.events) > 0 && after < r.events[0].EventID-1 {
		return nil, domain.Err("EVENT_CURSOR_EXPIRED", "Requested events have expired")
	}
	out := []domain.AgentEvent{}
	for _, v := range r.events {
		if v.EventID > after {
			out = append(out, clone(v))
			if len(out) == limit {
				break
			}
		}
	}
	return out, nil
}
func (a *Adapter) cancelRecord(r *record) {
	if domain.Terminal(r.job.Status) {
		return
	}
	r.cancelRequested = true
	if r.cancel != nil {
		r.cancel()
	}
	if r.job.Status == "queued" {
		r.job.Status = "cancelled"
		a.event(r, "warning", "cancelled", "Queued task cancelled")
	} else {
		a.event(r, "warning", "cancelling", "Cancellation requested")
	}
}
func (a *Adapter) Cancel(_ context.Context, id string) (domain.JobRecord, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "")
	if e != nil {
		return domain.JobRecord{}, e
	}
	if r.job.Status == "cancelled" {
		return clone(r.job), nil
	}
	if domain.Terminal(r.job.Status) {
		return domain.JobRecord{}, domain.Err("JOB_NOT_CANCELLABLE", "Completed or failed jobs cannot be cancelled")
	}
	if !r.cancelRequested {
		if r.job.JobType == "replay" {
			r.cancelRequested = true
			for _, id := range r.children {
				a.cancelRecord(a.jobs[id])
			}
			a.updateParent(r)
		} else {
			a.cancelRecord(r)
			if r.parent != "" {
				a.updateParent(a.jobs[r.parent])
			}
		}
	}
	return clone(r.job), nil
}
func (a *Adapter) counters(r *record) domain.ReplayCounters {
	c := domain.ReplayCounters{Total: len(r.children)}
	for _, id := range r.children {
		switch a.jobs[id].job.Status {
		case "queued":
			c.Queued++
		case "running":
			c.Running++
		case "completed":
			c.Completed++
		case "failed":
			c.Failed++
		case "cancelled":
			c.Cancelled++
		}
	}
	return c
}
func (a *Adapter) updateParent(p *record) {
	if domain.Terminal(p.job.Status) {
		return
	}
	c := a.counters(p)
	if c.Queued+c.Running == 0 {
		if p.cancelRequested || c.Cancelled > 0 {
			p.job.Status = "cancelled"
			a.event(p, "warning", "cancelled", "Replay cancelled; completed children preserved")
		} else if c.Failed > 0 {
			p.job.Status = "failed"
			code, msg := "REPLAY_CHILD_FAILED", "MOCK: One or more children failed"
			p.job.ErrorCode = &code
			p.job.ErrorMessage = &msg
			a.event(p, "failed", "failed", msg)
		} else {
			p.job.Status = "completed"
			a.event(p, "completed", "completed", "All replay children completed")
		}
	} else if p.job.Status == "queued" && (c.Running+c.Completed+c.Failed+c.Cancelled > 0) {
		p.job.Status = "running"
		a.event(p, "started", "running", "Replay children executing")
	}
}
func (a *Adapter) ReplayDetails(_ context.Context, id string) (domain.ReplayDetails, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "replay")
	if e != nil {
		return domain.ReplayDetails{}, e
	}
	c := a.counters(r)
	return domain.ReplayDetails{Job: clone(r.job), Request: clone(r.replay), CancelRequested: r.cancelRequested, Counters: c, HasFailures: c.Failed > 0}, nil
}
func (a *Adapter) ReplayRuns(_ context.Context, id string) ([]domain.JobRecord, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	r, e := a.find(id, "replay")
	if e != nil {
		return nil, e
	}
	out := []domain.JobRecord{}
	for _, id := range r.children {
		out = append(out, clone(a.jobs[id].job))
	}
	return out, nil
}

type cursor struct {
	Filter, ID string
	Created    time.Time
}

func encodeCursor(c cursor) string {
	b, _ := json.Marshal(c)
	return base64.RawURLEncoding.EncodeToString(b)
}
func decodeCursor(raw, filter string) (cursor, error) {
	var c cursor
	b, e := base64.RawURLEncoding.DecodeString(raw)
	if e != nil || len(b) > 2048 {
		return c, domain.Err("INVALID_CURSOR", "Invalid cursor")
	}
	if e = json.Unmarshal(b, &c); e != nil || c.Filter != filter || !domain.ValidID(c.ID) || c.Created.IsZero() {
		return c, domain.Err("INVALID_CURSOR", "Cursor does not match filters")
	}
	return c, nil
}
func (a *Adapter) ListForecasts(_ context.Context, f domain.ListFilter) (domain.ForecastList, error) {
	a.mu.Lock()
	defer a.mu.Unlock()
	var cur cursor
	var err error
	filter := fingerprint(f.FilterKey())
	if f.Cursor != "" {
		cur, err = decodeCursor(f.Cursor, filter)
		if err != nil {
			return domain.ForecastList{}, err
		}
	}
	rows := []*record{}
	for _, r := range a.jobs {
		if r.job.JobType != "forecast" {
			continue
		}
		q := r.request
		if f.From != nil && q.ForecastOrigin.Before(*f.From) || f.To != nil && !q.ForecastOrigin.Before(*f.To) || f.Status != "" && r.job.Status != f.Status || f.DataMode != "" && q.DataMode != f.DataMode || f.TurbineID != 0 && !slices.Contains(q.TurbineIDs, f.TurbineID) {
			continue
		}
		if f.Cursor != "" && (r.job.CreatedAt.After(cur.Created) || r.job.CreatedAt.Equal(cur.Created) && r.job.JobID >= cur.ID) {
			continue
		}
		rows = append(rows, r)
	}
	sort.Slice(rows, func(i, j int) bool {
		if rows[i].job.CreatedAt.Equal(rows[j].job.CreatedAt) {
			return rows[i].job.JobID > rows[j].job.JobID
		}
		return rows[i].job.CreatedAt.After(rows[j].job.CreatedAt)
	})
	out := domain.ForecastList{Items: []domain.ForecastRunDetails{}}
	for i, r := range rows {
		if i == f.Limit {
			last := rows[i-1]
			s := encodeCursor(cursor{filter, last.job.JobID, last.job.CreatedAt})
			out.NextCursor = &s
			break
		}
		out.Items = append(out.Items, a.details(r))
	}
	return out, nil
}
