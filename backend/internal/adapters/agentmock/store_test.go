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
func TestReplayCancellationPreservesCompletedChildren(t *testing.T){
 c:=&gateClock{make(chan struct{},10),make(chan struct{})};a:=New(Config{Workers:1,QueueCapacity:4,MaxJobs:10,MaxEvents:20,Scenario:"success"},c);defer a.Close();ctx:=context.Background();q:=mockRequest();p,e:=a.CreateReplay(ctx,domain.ReplayRequest{Origins:[]time.Time{q.ForecastOrigin,q.ForecastOrigin.Add(24*time.Hour)},HorizonHours:q.HorizonHours,TurbineIDs:q.TurbineIDs,ModelVersion:q.ModelVersion,DataMode:q.DataMode},domain.Operation{IdempotencyKey:"partial"});if e!=nil{t.Fatal(e)}
 <-c.entered;c.release<-struct{}{};<-c.entered;c.release<-struct{}{};<-c.entered
 if _,e=a.Cancel(ctx,p.JobID);e!=nil{t.Fatal(e)};a.Close();details,e:=a.ReplayDetails(ctx,p.JobID);if e!=nil{t.Fatal(e)};if details.Job.Status!="cancelled"||details.Counters.Completed!=1||details.Counters.Cancelled!=1{t.Fatalf("inconsistent partial replay: %+v",details)}
 children,_:=a.ReplayRuns(ctx,p.JobID);result,e:=a.ForecastResult(ctx,children[0].JobID);if e!=nil||len(result.Points)!=24{t.Fatal("completed child lost",e)}
}
func TestCompletionCancelRace(t *testing.T){for i:=0;i<20;i++{c:=&gateClock{make(chan struct{},10),make(chan struct{})};a:=New(Config{Workers:1,QueueCapacity:1,MaxJobs:2,MaxEvents:20,Scenario:"success"},c);ctx:=context.Background();j,e:=a.CreateForecast(ctx,mockRequest(),domain.Operation{IdempotencyKey:"race"});if e!=nil{t.Fatal(e)};<-c.entered;c.release<-struct{}{};<-c.entered;done:=make(chan struct{});go func(){_,_=a.Cancel(ctx,j.JobID);close(done)}();close(c.release);<-done;a.Close();j,e=a.GetJob(ctx,j.JobID);if e!=nil{t.Fatal(e)};r,e:=a.ForecastResult(ctx,j.JobID);switch j.Status{case "completed":if e!=nil||len(r.Points)!=24{t.Fatal("completed without result")};case "cancelled":if e==nil{t.Fatal("cancelled published result")};default:t.Fatal(j.Status)}}}
