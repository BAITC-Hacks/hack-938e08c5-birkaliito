package app

import (
	"context"
	"log/slog"
	"net/http"
	"os"
	"slices"
	"sync"
	"time"
	_ "time/tzdata"
	"wind/backend/api"
	"wind/backend/internal/adapters/agenthttp"
	"wind/backend/internal/adapters/agentmock"
	"wind/backend/internal/adapters/configrepo"
	"wind/backend/internal/application/catalog"
	"wind/backend/internal/application/evaluation"
	"wind/backend/internal/application/forecast"
	"wind/backend/internal/application/job"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/application/replay"
	httptransport "wind/backend/internal/transport/http"
	"wind/backend/internal/transport/http/handlers"
)

type SystemClock struct{}

func (SystemClock) Now() time.Time { return time.Now().UTC() }
func (SystemClock) Wait(ctx context.Context, d time.Duration) error {
	timer := time.NewTimer(d)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

type App struct {
	Server  *http.Server
	Handler http.Handler
	Logger  *slog.Logger
	stop    context.CancelFunc
	close   func()
	once    sync.Once
}

func New(cfg Config) (*App, error) {
	if e := cfg.Validate(); e != nil {
		return nil, e
	}
	v, e := api.NewValidator()
	if e != nil {
		return nil, e
	}
	log := slog.New(slog.NewJSONHandler(os.Stdout, &slog.HandlerOptions{Level: cfg.LogLevel}))
	clock := SystemClock{}
	var fg ports.ForecastGateway
	var jg ports.JobGateway
	var er ports.EventReader
	var rg ports.ReplayGateway
	var mc ports.ModelCatalog
	var ev ports.EvaluationReader
	var wr ports.WeatherReader
	var closeFn func()
	if cfg.AgentMode == "mock" {
		a := agentmock.New(agentmock.Config{Workers: cfg.Workers, QueueCapacity: cfg.QueueCapacity, MaxJobs: cfg.MaxJobs, MaxEvents: cfg.MaxEvents, Scenario: cfg.MockScenario, StepDelay: cfg.StepDelay}, clock)
		fg, jg, er, rg, mc, ev, wr = a, a, a, a, a, a, a
		closeFn = a.Close
	} else {
		a, err := agenthttp.New(agenthttp.Config{BaseURL: cfg.PythonBaseURL, Token: cfg.PythonToken, Timeout: cfg.UpstreamTimeout, ResponseLimit: cfg.ResponseLimit}, v)
		if err != nil {
			return nil, err
		}
		fg, jg, er, rg, mc, ev, wr = a, a, a, a, a, a, a
		closeFn = a.Close
	}
	f, e := forecast.NewForecastService(fg, clock, mc, wr, cfg.AllowFixtures)
	if e != nil {
		closeFn()
		return nil, e
	}
	j := job.NewJobService(jg, er, mc)
	r := replay.NewReplayService(rg, f, mc)
	c := catalog.NewCatalogService(mc, configrepo.New(cfg.Turbines), cfg.AgentMode, cfg.DisplayTimezone, cfg.AllowFixtures)
	eval := evaluation.NewEvaluationService(ev, mc)
	ctx, stop := context.WithCancel(context.Background())
	input := handlers.Input{Validator: v, BodyLimit: cfg.BodyLimit}
	router := httptransport.NewRouter(handlers.NewForecastHandler(f, input), handlers.NewJobHandler(j, cfg.PollInterval, cfg.Heartbeat, cfg.StreamWriteTimeout, cfg.MaxStreams, ctx), handlers.NewReplayHandler(r, input), handlers.NewCatalogHandler(c), handlers.NewEvaluationHandler(eval), log, slices.Clone(cfg.CORS), ctx)
	a := &App{Handler: router, Logger: log, stop: stop, close: closeFn}
	a.Server = &http.Server{Addr: cfg.HTTPAddr, Handler: router, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 15 * time.Second, IdleTimeout: 60 * time.Second, MaxHeaderBytes: 32 << 10}
	return a, nil
}
func (a *App) Shutdown(ctx context.Context) error {
	a.once.Do(func() { a.stop(); a.close() })
	return a.Server.Shutdown(ctx)
}
