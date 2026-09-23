package configrepo

import (
	"context"
	"slices"
	"wind/backend/internal/domain"
)

type Repository struct{ items []domain.Turbine }

func New(items []domain.Turbine) *Repository { return &Repository{items: copyItems(items)} }
func (r *Repository) Turbines(context.Context) (domain.TurbineList, error) {
	return domain.TurbineList{Items: copyItems(r.items)}, nil
}
func copyItems(items []domain.Turbine) []domain.Turbine {
	out := slices.Clone(items)
	for i := range out {
		if out[i].RatedPowerMW != nil {
			v := *out[i].RatedPowerMW
			out[i].RatedPowerMW = &v
		}
		if out[i].HubHeightM != nil {
			v := *out[i].HubHeightM
			out[i].HubHeightM = &v
		}
	}
	return out
}
