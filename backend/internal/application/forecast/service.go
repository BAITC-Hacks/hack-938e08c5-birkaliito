package forecast

import (
	"context"
	"errors"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/domain"
)

type Service struct {
	gateway       ports.ForecastGateway
	clock         ports.Clock
	catalog       ports.ModelCatalog
	weather       ports.WeatherReader
	allowFixtures bool
}

func NewForecastService(g ports.ForecastGateway, c ports.Clock, m ports.ModelCatalog, w ports.WeatherReader, allow bool) (*Service, error) {
	if g == nil || c == nil || m == nil || w == nil {
		return nil, errors.New("forecast dependencies required")
	}
	return &Service{g, c, m, w, allow}, nil
}
func (s *Service) CheckRequest(ctx context.Context, r domain.ForecastRequest) error {
	if r.DataMode == "fixture" && !s.allowFixtures {
		return domain.Err("FIXTURE_MODE_DISABLED", "Fixture mode is disabled")
	}
	models, err := s.catalog.Models(ctx)
	if err != nil {
		return err
	}
	for _, m := range models.Items {
		if m.ModelVersion == r.ModelVersion && m.DataMode == r.DataMode {
			if m.Availability != "ready" || !m.SupportsQuantiles {
				return domain.Invalid("model unavailable or quantiles unsupported")
			}
			if m.TrainingDataAvailableThrough.After(r.ForecastOrigin) {
				return domain.Invalid("model training cutoff exceeds origin")
			}
			return nil
		}
	}
	return domain.Err("DATA_MODE_MISMATCH", "Requested model and data mode are not available")
}
func (s *Service) Create(ctx context.Context, r domain.ForecastRequest, op domain.Operation) (domain.JobRecord, error) {
	r, err := domain.NormalizeRequest(r)
	if err != nil {
		return domain.JobRecord{}, err
	}
	if err = domain.ValidateKey(op.IdempotencyKey); err != nil {
		return domain.JobRecord{}, err
	}
	if err = s.CheckRequest(ctx, r); err != nil {
		return domain.JobRecord{}, err
	}
	j, err := s.gateway.CreateForecast(ctx, r, op)
	if err == nil {
		err = domain.ValidateJob(j)
		if j.JobType != "forecast" {
			err = domain.Violation("wrong job type")
		}
	}
	return j, err
}
func (s *Service) Details(ctx context.Context, id string) (domain.ForecastRunDetails, error) {
	return s.gateway.ForecastDetails(ctx, id)
}
func (s *Service) Result(ctx context.Context, id string) (domain.ForecastResult, error) {
	d, err := s.gateway.ForecastDetails(ctx, id)
	if err != nil {
		return domain.ForecastResult{}, err
	}
	r, err := s.gateway.ForecastResult(ctx, id)
	if err != nil {
		return r, err
	}
	return r, domain.ValidateResult(r, d.Request, id)
}
func (s *Service) List(ctx context.Context, f domain.ListFilter) (domain.ForecastList, error) {
	if err := f.Validate(); err != nil {
		return domain.ForecastList{}, err
	}
	return s.gateway.ListForecasts(ctx, f)
}
func (s *Service) Weather(ctx context.Context, id string) (domain.WeatherDetails, error) {
	c, err := s.catalog.Capabilities(ctx)
	if err != nil {
		return domain.WeatherDetails{}, err
	}
	if !c.WeatherDetails {
		return domain.WeatherDetails{}, domain.Err("FEATURE_NOT_SUPPORTED", "Weather details unsupported")
	}
	return s.weather.Weather(ctx, id)
}
func (s *Service) Explanation(ctx context.Context, id string) (domain.ExplanationDetails, error) {
	return s.gateway.Explanation(ctx, id)
}
