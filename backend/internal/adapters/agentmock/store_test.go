package agentmock

import (
	"context"
	"sync"
	"testing"
	"time"
	"wind/backend/internal/domain"
)

type gateClock struct {
	entered chan struct{}
	release chan struct{}
}

func (c *gateClock) Now() time.Time { return time.Date(2026, 9, 23, 10, 0, 0, 0, time.UTC) }
func (c *gateClock) Wait(ctx context.Context, _ time.Duration) error {
	select {
	case c.entered <- struct{}{}:
	default:
	}
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-c.release:
		return nil
	}
}
func mockRequest() domain.ForecastRequest {
	return domain.ForecastRequest{ForecastOrigin: time.Date(2026, 1, 31, 18, 0, 0, 0, time.UTC), HorizonHours: 24, TurbineIDs: []int{1}, ModelVersion: "fixture-not-trained", Mode: "replay", DataMode: "fixture"}
}
func TestBoundedQueueCancellationAndCopies(t *testing.T) {
	c := &gateClock{make(chan struct{}, 10), make(chan struct{})}
	a := New(Config{Workers: 1, QueueCapacity: 1, MaxJobs: 5, MaxEvents: 2, Scenario: "success"}, c)
	defer a.Close()
	ctx := context.Background()
	j, e := a.CreateForecast(ctx, mockRequest(), domain.Operation{IdempotencyKey: "a"})
	if e != nil {
		t.Fatal(e)
	}
	<-c.entered
	queued, e := a.CreateForecast(ctx, mockRequest(), domain.Operation{IdempotencyKey: "b"})
	if e != nil {
		t.Fatal(e)
	}
	if _, e = a.CreateForecast(ctx, mockRequest(), domain.Operation{IdempotencyKey: "c"}); e == nil {
		t.Fatal("queue not bounded")
	}
	if len(a.jobs) != 2 {
		t.Fatal("orphan created")
	}
	duplicate, e := a.CreateForecast(ctx, mockRequest(), domain.Operation{IdempotencyKey: "b"})
	if e != nil || duplicate.JobID != queued.JobID {
		t.Fatal("idempotent retry on full queue")
	}
	cancelled, e := a.Cancel(ctx, queued.JobID)
	if e != nil || cancelled.Status != "cancelled" {
		t.Fatal("queued cancellation")
	}
	if _, e = a.Cancel(ctx, j.JobID); e != nil {
		t.Fatal(e)
	}
	close(c.release)
	a.Close()
	finished, _ := a.GetJob(ctx, j.JobID)
	if finished.Status != "cancelled" {
		t.Fatal("running cancellation")
	}
	d, _ := a.ForecastDetails(ctx, j.JobID)
	d.Request.TurbineIDs[0] = 99
	again, _ := a.ForecastDetails(ctx, j.JobID)
	if again.Request.TurbineIDs[0] != 1 {
		t.Fatal("store alias escaped")
	}
	if _, e = a.Events(ctx, j.JobID, 0, 100); e == nil {
		t.Fatal("retention expiration not reported")
	}
}
func TestConcurrentIdempotency(t *testing.T) {
	c := &gateClock{make(chan struct{}, 100), make(chan struct{})}
	a := New(Config{Workers: 2, QueueCapacity: 32, MaxJobs: 100, MaxEvents: 20, Scenario: "success"}, c)
	defer a.Close()
	var wg sync.WaitGroup
	ids := make(chan string, 40)
	errs := make(chan error, 40)
	for i := 0; i < 40; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			j, e := a.CreateForecast(context.Background(), mockRequest(), domain.Operation{IdempotencyKey: "one"})
			if e != nil {
				errs <- e
			} else {
				ids <- j.JobID
			}
		}()
	}
	wg.Wait()
	close(ids)
	close(errs)
	for e := range errs {
		t.Fatal(e)
	}
	id := ""
	for v := range ids {
		if id != "" && id != v {
			t.Fatal("duplicate job")
		}
		id = v
	}
	a.mu.Lock()
	n := len(a.jobs)
	a.mu.Unlock()
	if n != 1 {
		t.Fatal(n)
	}
	close(c.release)
}
