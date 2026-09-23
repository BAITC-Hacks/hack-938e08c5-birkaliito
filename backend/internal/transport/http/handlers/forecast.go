package handlers

import (
	"context"
	"github.com/gin-gonic/gin"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
	"wind/backend/internal/transport/http/responses"
)

type ForecastUseCase interface {
	Create(context.Context, domain.ForecastRequest, domain.Operation) (domain.JobRecord, error)
	Details(context.Context, string) (domain.ForecastRunDetails, error)
	Result(context.Context, string) (domain.ForecastResult, error)
	List(context.Context, domain.ListFilter) (domain.ForecastList, error)
	Weather(context.Context, string) (domain.WeatherDetails, error)
	Explanation(context.Context, string) (domain.ExplanationDetails, error)
}
type ForecastHandler struct {
	service ForecastUseCase
	input   Input
}

func NewForecastHandler(s ForecastUseCase, i Input) *ForecastHandler { return &ForecastHandler{s, i} }
func (h *ForecastHandler) Create(c *gin.Context) {
	q := dto.ForecastRequest{HorizonHours: 48, TurbineIDs: []int{1, 2}, Mode: "replay", DataMode: "real"}
	if !h.input.Decode(c, "ForecastRequest", &q) {
		return
	}
	v, e := h.service.Create(c.Request.Context(), dto.ForecastRequestToDomain(q), domain.Operation{RequestID: c.GetString("request_id"), IdempotencyKey: c.GetHeader("Idempotency-Key")})
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(202, dto.JobRecordFromDomain(v))
}
func (h *ForecastHandler) Details(c *gin.Context) {
	v, e := h.service.Details(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.ForecastRunDetailsFromDomain(v))
}
func (h *ForecastHandler) Result(c *gin.Context) {
	v, e := h.service.Result(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.ForecastResultFromDomain(v))
}
func (h *ForecastHandler) List(c *gin.Context) {
	f, e := listFilter(c, true)
	if e != nil {
		responses.Error(c, e)
		return
	}
	v, e := h.service.List(c.Request.Context(), f)
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.ForecastListFromDomain(v))
}
func (h *ForecastHandler) Weather(c *gin.Context) {
	v, e := h.service.Weather(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.WeatherDetailsFromDomain(v))
}
func (h *ForecastHandler) Explanation(c *gin.Context) {
	v, e := h.service.Explanation(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.ExplanationDetailsFromDomain(v))
}
func (h *ForecastHandler) Export(c *gin.Context) {
	v, e := h.service.Result(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	writeCSV(c, []domain.ForecastResult{v}, c.Param("id"))
}
