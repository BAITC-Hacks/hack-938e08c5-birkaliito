package handlers

import (
	"bufio"
	"context"
	"github.com/gin-gonic/gin"
	"net/http"
	"net/http/httptest"
	"sync/atomic"
	"testing"
	"time"
	"wind/backend/internal/domain"
)

type blockedJobs struct {
	calls   atomic.Int32
	stopped chan struct{}
}

func (f *blockedJobs) CanStream(context.Context) error { return nil }
func (f *blockedJobs) Get(ctx context.Context, id string) (domain.JobRecord, error) {
	if f.calls.Add(1) > 1 {
		<-ctx.Done()
		close(f.stopped)
		return domain.JobRecord{}, ctx.Err()
	}
	return domain.JobRecord{JobID: id, Status: "running"}, nil
}
func (f *blockedJobs) Events(context.Context, string, int64, int) ([]domain.AgentEvent, error) {
	return []domain.AgentEvent{}, nil
}
func (f *blockedJobs) Cancel(context.Context, string) (domain.JobRecord, error) {
	panic("disconnect must not cancel job")
}
func TestHeartbeatContinuesDuringSlowUpstreamAndPollerStops(t *testing.T) {
	fake := &blockedJobs{stopped: make(chan struct{})}
	h := NewJobHandler(fake, time.Millisecond, 5*time.Millisecond, time.Second, 1, context.Background())
	r := gin.New()
	r.GET("/jobs/:id/stream", h.Stream)
	s := httptest.NewServer(r)
	defer s.Close()
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	req, _ := http.NewRequestWithContext(ctx, "GET", s.URL+"/jobs/test-job/stream", nil)
	client := &http.Client{Timeout: time.Second}
	resp, e := client.Do(req)
	if e != nil {
		t.Fatal(e)
	}
	line, e := bufio.NewReader(resp.Body).ReadString('\n')
	if e != nil || line != ": heartbeat\n" {
		t.Fatal(line, e)
	}
	cancel()
	resp.Body.Close()
	select {
	case <-fake.stopped:
	case <-time.After(time.Second):
		t.Fatal("stream poller leaked")
	}
}
