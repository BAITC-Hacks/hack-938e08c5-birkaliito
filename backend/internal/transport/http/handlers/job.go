package handlers

import (
	"context"
	"encoding/json"
	"fmt"
	"github.com/gin-gonic/gin"
	"net/http"
	"strconv"
	"time"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
	"wind/backend/internal/transport/http/responses"
)

type JobUseCase interface {
	CanStream(context.Context) error
	Get(context.Context, string) (domain.JobRecord, error)
	Events(context.Context, string, int64, int) ([]domain.AgentEvent, error)
	Cancel(context.Context, string) (domain.JobRecord, error)
}
type JobHandler struct {
	service                       JobUseCase
	poll, heartbeat, writeTimeout time.Duration
	slots                         chan struct{}
	lifecycle                     context.Context
}

func NewJobHandler(s JobUseCase, poll, heartbeat, writeTimeout time.Duration, maxStreams int, lifecycle context.Context) *JobHandler {
	return &JobHandler{s, poll, heartbeat, writeTimeout, make(chan struct{}, maxStreams), lifecycle}
}
func (h *JobHandler) Get(c *gin.Context) {
	v, e := h.service.Get(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.JobRecordFromDomain(v))
}
func (h *JobHandler) Cancel(c *gin.Context) {
	v, e := h.service.Cancel(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	code := 202
	if v.Status == "cancelled" {
		code = 200
	}
	c.JSON(code, dto.JobRecordFromDomain(v))
}
func (h *JobHandler) Events(c *gin.Context) {
	after, limit, e := eventQuery(c)
	if e != nil {
		responses.Error(c, e)
		return
	}
	v, e := h.service.Events(c.Request.Context(), c.Param("id"), after, limit)
	if e != nil {
		responses.Error(c, e)
		return
	}
	out := make([]dto.AgentEvent, len(v))
	for i, item := range v {
		out[i] = dto.AgentEventFromDomain(item)
	}
	c.JSON(200, out)
}
func (h *JobHandler) Stream(c *gin.Context) {
	after, limit, e := eventQuery(c)
	if e != nil {
		responses.Error(c, e)
		return
	}
	if values := c.Request.Header.Values("Last-Event-ID"); len(values) > 0 {
		raw := values[0]
		valid := len(values) == 1 && raw != ""
		for _, ch := range raw {
			if ch < '0' || ch > '9' {
				valid = false
			}
		}
		v, err := strconv.ParseInt(raw, 10, 64)
		if !valid || err != nil || v < 0 || v > 9007199254740991 {
			responses.Error(c, domain.Err("INVALID_CURSOR", "Invalid Last-Event-ID"))
			return
		}
		after = v
	}
	select {
	case <-h.lifecycle.Done():
		responses.Error(c, domain.Err("DEPENDENCY_UNAVAILABLE", "Server stopping"))
		return
	default:
	}
	select {
	case h.slots <- struct{}{}:
		defer func() { <-h.slots }()
	default:
		responses.Error(c, domain.Err("RATE_LIMITED", "Too many event streams"))
		return
	}
	ctx, cancel := context.WithCancel(c.Request.Context())
	defer cancel()
	stop := context.AfterFunc(h.lifecycle, cancel)
	defer stop()
	id := c.Param("id")
	if e = h.service.CanStream(ctx); e != nil {
		responses.Error(c, e)
		return
	}
	j, e := h.service.Get(ctx, id)
	if e != nil {
		responses.Error(c, e)
		return
	}
	events, e := h.service.Events(ctx, id, after, limit)
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.Header("Content-Type", "text/event-stream")
	c.Header("Cache-Control", "no-cache")
	c.Header("X-Accel-Buffering", "no")
	rc := http.NewResponseController(c.Writer)
	write := func(kind string, v any, eventID int64) bool {
		_ = rc.SetWriteDeadline(time.Now().Add(h.writeTimeout))
		b, err := json.Marshal(v)
		if err != nil {
			return false
		}
		var text string
		if eventID > 0 {
			text = fmt.Sprintf("id: %d\n", eventID)
		}
		_, err = fmt.Fprintf(c.Writer, "%sevent: %s\ndata: %s\n\n", text, kind, b)
		if err != nil {
			return false
		}
		return rc.Flush() == nil
	}
	ticker := time.NewTicker(h.poll)
	defer ticker.Stop()
	heart := time.NewTicker(h.heartbeat)
	defer heart.Stop()
	for {
		for _, ev := range events {
			if !write("agent_event", dto.AgentEventFromDomain(ev), ev.EventID) {
				return
			}
			after = ev.EventID
		}
		// Read terminal status before a fresh tail read. The immutable terminal log cannot grow afterwards.
		j, e = h.service.Get(ctx, id)
		if e == nil {
			events, e = h.service.Events(ctx, id, after, limit)
		}
		if e != nil {
			if ctx.Err() == nil {
				write("stream_error", dto.ApiError{Code: "STREAM_UNAVAILABLE", Message: "Event stream interrupted; reconnect or poll", RequestID: ptr(c.GetString("request_id"))}, 0)
			}
			return
		}
		if len(events) > 0 {
			continue
		}
		if domain.Terminal(j.Status) {
			write("stream_end", dto.StreamEnd{JobID: id, Status: j.Status}, 0)
			return
		}
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		case <-heart.C:
			_ = rc.SetWriteDeadline(time.Now().Add(h.writeTimeout))
			if _, e = fmt.Fprint(c.Writer, ": heartbeat\n\n"); e != nil {
				return
			}
			if rc.Flush() != nil {
				return
			}
		}
	}
}
func ptr(s string) *string { return &s }
