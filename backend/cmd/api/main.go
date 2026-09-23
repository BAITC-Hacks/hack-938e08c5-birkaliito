package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os/signal"
	"syscall"
	"wind/backend/internal/app"
)

func main() {
	cfg, e := app.LoadConfig()
	if e != nil {
		log.Fatal(e)
	}
	a, e := app.New(cfg)
	if e != nil {
		log.Fatal(e)
	}
	ctx, stop := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer stop()
	errs := make(chan error, 1)
	go func() {
		a.Logger.Info("server starting", "addr", cfg.HTTPAddr, "agent_mode", cfg.AgentMode)
		errs <- a.Server.ListenAndServe()
	}()
	select {
	case <-ctx.Done():
	case e = <-errs:
		if e != nil && !errors.Is(e, http.ErrServerClosed) {
			a.Logger.Error("server stopped", "error", e)
		}
	}
	shutdown, cancel := context.WithTimeout(context.Background(), cfg.ShutdownTimeout)
	defer cancel()
	if e = a.Shutdown(shutdown); e != nil {
		a.Logger.Error("shutdown", "error", e)
	}
}
