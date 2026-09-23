package app

import (
	"fmt"
	"log/slog"
	"math"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
	"wind/backend/internal/domain"
)

type Config struct {
	Env, HTTPAddr, AgentMode, PythonBaseURL, PythonToken, DisplayTimezone, MockScenario      string
	AllowFixtures                                                                            bool
	LogLevel                                                                                 slog.Level
	CORS                                                                                     []string
	Workers, QueueCapacity, MaxJobs, MaxEvents, MaxStreams                                   int
	BodyLimit, ResponseLimit                                                                 int64
	UpstreamTimeout, ShutdownTimeout, StepDelay, Heartbeat, PollInterval, StreamWriteTimeout time.Duration
	Turbines                                                                                 []domain.Turbine
}

func DefaultConfig() Config {
	return Config{Env: "development", HTTPAddr: "127.0.0.1:8080", AgentMode: "mock", AllowFixtures: true, PythonBaseURL: "http://localhost:8000", DisplayTimezone: "Asia/Almaty", MockScenario: "success", CORS: []string{"http://localhost:5173"}, Workers: 2, QueueCapacity: 64, MaxJobs: 500, MaxEvents: 2000, MaxStreams: 64, BodyLimit: 1 << 20, ResponseLimit: 8 << 20, UpstreamTimeout: 20 * time.Second, ShutdownTimeout: 10 * time.Second, StepDelay: 100 * time.Millisecond, Heartbeat: 15 * time.Second, PollInterval: time.Second, StreamWriteTimeout: 10 * time.Second, Turbines: []domain.Turbine{{ID: 1, Name: "Turbine 1", Latitude: 43.645150, Longitude: 78.535604, MetadataStatus: "configured_unverified"}, {ID: 2, Name: "Turbine 2", Latitude: 43.643198, Longitude: 78.538828, MetadataStatus: "configured_unverified"}}}
}
func LoadConfig() (Config, error) {
	c := DefaultConfig()
	for key, dst := range map[string]*string{"APP_ENV": &c.Env, "HTTP_ADDR": &c.HTTPAddr, "AGENT_MODE": &c.AgentMode, "PYTHON_BASE_URL": &c.PythonBaseURL, "PYTHON_INTERNAL_TOKEN": &c.PythonToken, "DISPLAY_TIMEZONE": &c.DisplayTimezone, "MOCK_SCENARIO": &c.MockScenario} {
		if s, ok := os.LookupEnv(key); ok {
			*dst = s
		}
	}
	if s, ok := os.LookupEnv("ALLOW_FIXTURES"); ok {
		v, e := strconv.ParseBool(s)
		if e != nil {
			return c, fmt.Errorf("ALLOW_FIXTURES: %w", e)
		}
		c.AllowFixtures = v
	} else if c.Env == "production" || c.AgentMode == "http" {
		c.AllowFixtures = false
	}
	if s, ok := os.LookupEnv("LOG_LEVEL"); ok {
		if e := c.LogLevel.UnmarshalText([]byte(s)); e != nil {
			return c, e
		}
	}
	if s, ok := os.LookupEnv("CORS_ALLOWED_ORIGINS"); ok {
		c.CORS = []string{}
		for _, v := range strings.Split(s, ",") {
			if v = strings.TrimSpace(v); v != "" {
				c.CORS = append(c.CORS, v)
			}
		}
	}
	for key, dst := range map[string]*int{"MOCK_WORKERS": &c.Workers, "MOCK_QUEUE_CAPACITY": &c.QueueCapacity, "MOCK_MAX_JOBS": &c.MaxJobs, "MOCK_MAX_EVENTS_PER_JOB": &c.MaxEvents, "SSE_MAX_STREAMS": &c.MaxStreams} {
		if s, ok := os.LookupEnv(key); ok {
			v, e := strconv.Atoi(s)
			if e != nil {
				return c, fmt.Errorf("%s: %w", key, e)
			}
			*dst = v
		}
	}
	for key, dst := range map[string]*int64{"HTTP_BODY_LIMIT": &c.BodyLimit, "UPSTREAM_RESPONSE_LIMIT": &c.ResponseLimit} {
		if s, ok := os.LookupEnv(key); ok {
			v, e := strconv.ParseInt(s, 10, 64)
			if e != nil {
				return c, fmt.Errorf("%s: %w", key, e)
			}
			*dst = v
		}
	}
	for key, dst := range map[string]*time.Duration{"UPSTREAM_TIMEOUT": &c.UpstreamTimeout, "SHUTDOWN_TIMEOUT": &c.ShutdownTimeout, "MOCK_STEP_DELAY": &c.StepDelay, "SSE_HEARTBEAT_INTERVAL": &c.Heartbeat, "EVENT_POLL_INTERVAL": &c.PollInterval, "SSE_WRITE_TIMEOUT": &c.StreamWriteTimeout} {
		if s, ok := os.LookupEnv(key); ok {
			v, e := time.ParseDuration(s)
			if e != nil {
				return c, fmt.Errorf("%s: %w", key, e)
			}
			*dst = v
		}
	}
	for i := range c.Turbines {
		for suffix, dst := range map[string]*float64{"LATITUDE": &c.Turbines[i].Latitude, "LONGITUDE": &c.Turbines[i].Longitude} {
			key := fmt.Sprintf("TURBINE_%d_%s", i+1, suffix)
			if s, ok := os.LookupEnv(key); ok {
				v, e := strconv.ParseFloat(s, 64)
				if e != nil {
					return c, e
				}
				*dst = v
			}
		}
	}
	return c, c.Validate()
}
func (c Config) Validate() error {
	if c.Env != "development" && c.Env != "test" && c.Env != "production" {
		return fmt.Errorf("invalid APP_ENV")
	}
	if c.AgentMode != "mock" && c.AgentMode != "http" {
		return fmt.Errorf("AGENT_MODE must be mock or http")
	}
	if c.Env == "production" && c.AllowFixtures {
		return fmt.Errorf("production prohibits fixtures")
	}
	if c.AgentMode == "mock" && !c.AllowFixtures {
		return fmt.Errorf("mock requires ALLOW_FIXTURES=true")
	}
	if c.AgentMode == "http" && c.AllowFixtures {
		return fmt.Errorf("http mode only accepts real data; disable fixtures")
	}
	switch c.MockScenario {
	case "success", "degraded", "failure", "slow", "llm_unavailable", "weather_future":
	default:
		return fmt.Errorf("unknown MOCK_SCENARIO")
	}
	for _, n := range []int{c.Workers, c.QueueCapacity, c.MaxJobs, c.MaxEvents, c.MaxStreams} {
		if n <= 0 || n > 100000 {
			return fmt.Errorf("resource limits must be 1..100000")
		}
	}
	if c.BodyLimit <= 0 || c.ResponseLimit <= 0 || c.BodyLimit > 64<<20 || c.ResponseLimit > 64<<20 {
		return fmt.Errorf("body limits must be 1..64 MiB")
	}
	for _, d := range []time.Duration{c.UpstreamTimeout, c.ShutdownTimeout, c.Heartbeat, c.PollInterval, c.StreamWriteTimeout} {
		if d <= 0 {
			return fmt.Errorf("timeouts and intervals must be positive")
		}
	}
	if c.StepDelay < 0 {
		return fmt.Errorf("MOCK_STEP_DELAY cannot be negative")
	}
	if _, e := time.LoadLocation(c.DisplayTimezone); e != nil {
		return fmt.Errorf("invalid DISPLAY_TIMEZONE: %w", e)
	}
	if c.HTTPAddr == "" {
		return fmt.Errorf("HTTP_ADDR required")
	}
	u, e := url.Parse(c.PythonBaseURL)
	if e != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return fmt.Errorf("invalid trusted PYTHON_BASE_URL")
	}
	for _, origin := range c.CORS {
		u, e := url.Parse(origin)
		if e != nil || u.Host == "" || u.User != nil || u.Path != "" || u.RawQuery != "" || u.Fragment != "" || (u.Scheme != "http" && u.Scheme != "https") {
			return fmt.Errorf("CORS origins must be exact HTTP(S) origins")
		}
	}
	if len(c.Turbines) != 2 {
		return fmt.Errorf("configure two turbines")
	}
	for i, t := range c.Turbines {
		if t.ID != i+1 || math.IsNaN(t.Latitude) || math.IsNaN(t.Longitude) || t.Latitude < -90 || t.Latitude > 90 || t.Longitude < -180 || t.Longitude > 180 {
			return fmt.Errorf("invalid turbine configuration")
		}
	}
	return nil
}
