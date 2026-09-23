package configrepo

import (
	"context"
	"slices"
	"wind/backend/internal/domain"
)

type Repository struct{ items []domain.Turbine }

func New(items []domain.Turbine) *Repository { return &Repository{items: slices.Clone(items)} }
func (r *Repository) Turbines(context.Context) (domain.TurbineList, error) {
	return domain.TurbineList{Items: slices.Clone(r.items)}, nil
}
