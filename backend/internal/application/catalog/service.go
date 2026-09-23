package catalog

import (
	"context"
	"time"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/domain"
)

type Service struct {
	models         ports.ModelCatalog
	turbines       ports.TurbineRepository
	mode, timezone string
	fixtures       bool
}

func NewCatalogService(m ports.ModelCatalog, t ports.TurbineRepository, mode, tz string, fixtures bool) *Service {
	return &Service{m, t, mode, tz, fixtures}
}
func (s *Service) Ready(ctx context.Context) error {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	return s.models.Ready(ctx)
}
func (s *Service) Meta(ctx context.Context) domain.Meta {
	ctx, cancel := context.WithTimeout(ctx, 2*time.Second)
	defer cancel()
	m := domain.Meta{Service: "wind-forecast", Version: "0.1.0", ContractVersion: "1.1.0", AgentMode: s.mode, DisplayTimezone: s.timezone, SourceTimezoneStatus: "unconfirmed", TargetUnit: "normalized_power", NormalizationStatus: "unconfirmed", AgentDependency: "unavailable", AllowedDataModes: []string{}}
	c, e := s.models.Capabilities(ctx)
	if e == nil {
		m.Capabilities = c
		if s.models.Ready(ctx) == nil {
			m.AgentDependency = "available"
		}
	}
	if s.mode == "mock" {
		m.Capabilities.Simulated = true
		if s.fixtures {
			m.AllowedDataModes = []string{"fixture"}
		}
	} else {
		m.AllowedDataModes = []string{"real"}
	}
	return m
}
func (s *Service) Models(ctx context.Context) (domain.ModelList, error) { return s.models.Models(ctx) }
func (s *Service) Turbines(ctx context.Context) (domain.TurbineList, error) {
	return s.turbines.Turbines(ctx)
}
