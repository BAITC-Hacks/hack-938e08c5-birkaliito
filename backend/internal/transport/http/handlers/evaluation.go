package handlers

import (
	"context"
	"github.com/gin-gonic/gin"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
	"wind/backend/internal/transport/http/responses"
)

type EvaluationUseCase interface {
	List(context.Context, domain.ListFilter) (domain.EvaluationList, error)
	Get(context.Context, string) (domain.EvaluationReport, error)
	Quality(context.Context) (domain.DataQualityReport, error)
}
type EvaluationHandler struct{ service EvaluationUseCase }

func NewEvaluationHandler(s EvaluationUseCase) *EvaluationHandler { return &EvaluationHandler{s} }
func (h *EvaluationHandler) List(c *gin.Context) {
	f, e := listFilter(c, false)
	if e != nil {
		responses.Error(c, e)
		return
	}
	v, e := h.service.List(c.Request.Context(), f)
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.EvaluationListFromDomain(v))
}
func (h *EvaluationHandler) Get(c *gin.Context) {
	v, e := h.service.Get(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.EvaluationReportFromDomain(v))
}
func (h *EvaluationHandler) Quality(c *gin.Context) {
	v, e := h.service.Quality(c.Request.Context())
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.DataQualityReportFromDomain(v))
}
