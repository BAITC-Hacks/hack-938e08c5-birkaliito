package evaluation

import (
	"context"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/domain"
)

type Service struct {
	reader  ports.EvaluationReader
	catalog ports.ModelCatalog
}

func NewEvaluationService(r ports.EvaluationReader, c ports.ModelCatalog) *Service {
	return &Service{r, c}
}
func (s *Service) supported(ctx context.Context, quality bool) error {
	c, e := s.catalog.Capabilities(ctx)
	if e != nil {
		return e
	}
	if (quality && !c.DataQuality) || (!quality && !c.Evaluations) {
		return domain.Err("FEATURE_NOT_SUPPORTED", "Requested read model unsupported")
	}
	return nil
}
func (s *Service) List(ctx context.Context, f domain.ListFilter) (domain.EvaluationList, error) {
	if e := f.Validate(); e != nil {
		return domain.EvaluationList{}, e
	}
	if e := s.supported(ctx, false); e != nil {
		return domain.EvaluationList{}, e
	}
	return s.reader.Evaluations(ctx, f)
}
func (s *Service) Get(ctx context.Context, id string) (domain.EvaluationReport, error) {
	if e := s.supported(ctx, false); e != nil {
		return domain.EvaluationReport{}, e
	}
	return s.reader.Evaluation(ctx, id)
}
func (s *Service) Quality(ctx context.Context) (domain.DataQualityReport, error) {
	if e := s.supported(ctx, true); e != nil {
		return domain.DataQualityReport{}, e
	}
	return s.reader.DataQuality(ctx)
}
