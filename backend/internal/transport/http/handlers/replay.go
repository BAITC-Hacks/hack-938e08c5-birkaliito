package handlers

import (
	"context"
	"github.com/gin-gonic/gin"
	"strconv"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
	"wind/backend/internal/transport/http/responses"
)

type ReplayUseCase interface {
	Create(context.Context, domain.ReplayRequest, domain.Operation) (domain.JobRecord, error)
	Details(context.Context, string) (domain.ReplayDetails, error)
	Runs(context.Context, string) ([]domain.JobRecord, error)
	Export(context.Context, string, bool) (domain.Export, error)
}
type ReplayHandler struct {
	service ReplayUseCase
	input   Input
}

func NewReplayHandler(s ReplayUseCase, i Input) *ReplayHandler { return &ReplayHandler{s, i} }
func (h *ReplayHandler) Create(c *gin.Context) {
	q := dto.ReplayRequest{HorizonHours: 48, TurbineIDs: []int{1, 2}, DataMode: "real"}
	if !h.input.Decode(c, "ReplayRequest", &q) {
		return
	}
	v, e := h.service.Create(c.Request.Context(), dto.ReplayRequestToDomain(q), domain.Operation{RequestID: c.GetString("request_id"), IdempotencyKey: c.GetHeader("Idempotency-Key")})
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(202, dto.JobRecordFromDomain(v))
}
func (h *ReplayHandler) Details(c *gin.Context) {
	v, e := h.service.Details(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	c.JSON(200, dto.ReplayDetailsFromDomain(v))
}
func (h *ReplayHandler) Runs(c *gin.Context) {
	v, e := h.service.Runs(c.Request.Context(), c.Param("id"))
	if e != nil {
		responses.Error(c, e)
		return
	}
	out := make([]dto.JobRecord, len(v))
	for i, item := range v {
		out[i] = dto.JobRecordFromDomain(item)
	}
	c.JSON(200, out)
}
func (h *ReplayHandler) Export(c *gin.Context) {
	if e := checkQuery(c, "allow_partial"); e != nil {
		responses.Error(c, e)
		return
	}
	partial := false
	if values, ok := c.Request.URL.Query()["allow_partial"]; ok {
		if values[0] != "true" && values[0] != "false" {
			responses.Error(c, domain.Invalid("allow_partial must be true or false"))
			return
		}
		partial = values[0] == "true"
	}
	v, e := h.service.Export(c.Request.Context(), c.Param("id"), partial)
	if e != nil {
		responses.Error(c, e)
		return
	}
	label := "complete"
	if v.Partial {
		label = "partial"
	}
	c.Header("X-Replay-Export-Status", label)
	for k, n := range map[string]int{"Total": v.Counters.Total, "Completed": v.Counters.Completed, "Failed": v.Counters.Failed, "Cancelled": v.Counters.Cancelled} {
		c.Header("X-Replay-"+k, strconv.Itoa(n))
	}
	writeCSV(c, v.Results, c.Param("id"))
}
