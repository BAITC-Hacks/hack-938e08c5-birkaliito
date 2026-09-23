package handlers

import (
	"context"
	"github.com/gin-gonic/gin"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
	"wind/backend/internal/transport/http/responses"
)

type CatalogUseCase interface {
	Ready(context.Context) error
	Meta(context.Context) domain.Meta
	Models(context.Context) (domain.ModelList, error)
	Turbines(context.Context) (domain.TurbineList, error)
}
type CatalogHandler struct{ service CatalogUseCase }

func NewCatalogHandler(s CatalogUseCase) *CatalogHandler { return &CatalogHandler{s} }
func (h *CatalogHandler) Ready(c *gin.Context) {
	if e := h.service.Ready(c.Request.Context()); e != nil {
		responses.Error(c, domain.Wrap("DEPENDENCY_UNAVAILABLE", "Agent dependency not ready", e))
		return
	}
	c.JSON(200, dto.Health{Status: "ok"})
}
func (h *CatalogHandler) Meta(c *gin.Context) {
	c.JSON(200, dto.MetaFromDomain(h.service.Meta(c.Request.Context())))
}
func (h *CatalogHandler) Models(c *gin.Context) {
	v, e := h.service.Models(c.Request.Context())
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.ModelListFromDomain(v))
}
func (h *CatalogHandler) Turbines(c *gin.Context) {
	v, e := h.service.Turbines(c.Request.Context())
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.TurbineListFromDomain(v))
}
