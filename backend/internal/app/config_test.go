package app

import (
	"testing"
	"time"
)

func TestConfigRejectsContradictions(t *testing.T) {
	for name, edit := range map[string]func(*Config){"production fixture": func(c *Config) { c.Env = "production" }, "zero queue": func(c *Config) { c.QueueCapacity = 0 }, "negative delay": func(c *Config) { c.StepDelay = -time.Second }, "unknown scenario": func(c *Config) { c.MockScenario = "random" }, "http fixture": func(c *Config) { c.AgentMode = "http" }, "wildcard cors": func(c *Config) { c.CORS = []string{"*"} }, "untrusted url": func(c *Config) { c.PythonBaseURL = "file:///secret" }} {
		t.Run(name, func(t *testing.T) {
			c := DefaultConfig()
			edit(&c)
			if c.Validate() == nil {
				t.Fatal("invalid config accepted")
			}
		})
	}
}
