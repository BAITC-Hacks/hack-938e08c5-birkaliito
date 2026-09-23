package handlers

import (
	"encoding/json"
	"errors"
	"github.com/gin-gonic/gin"
	"io"
	"mime"
	"net/http"
	"strconv"
	"time"
	"wind/backend/api"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/responses"
)

type Input struct {
	Validator *api.Validator
	BodyLimit int64
}

func (i Input) Decode(c *gin.Context, name string, out any) bool {
	media, _, e := mime.ParseMediaType(c.GetHeader("Content-Type"))
	if e != nil || media != "application/json" {
		responses.Error(c, domain.Err("UNSUPPORTED_MEDIA_TYPE", "Content-Type must be application/json"))
		return false
	}
	c.Request.Body = http.MaxBytesReader(c.Writer, c.Request.Body, i.BodyLimit)
	b, e := io.ReadAll(c.Request.Body)
	if e != nil {
		var limit *http.MaxBytesError
		if errors.As(e, &limit) {
			responses.Error(c, domain.Err("BODY_TOO_LARGE", "Request body exceeds configured limit"))
		} else {
			responses.Error(c, domain.Err("BAD_JSON", "Cannot read request JSON"))
		}
		return false
	}
	if !json.Valid(b) {
		responses.Error(c, domain.Err("BAD_JSON", "Malformed or trailing JSON"))
		return false
	}
	if e = i.Validator.Validate(name, b); e != nil {
		responses.Error(c, domain.Wrap("VALIDATION_ERROR", "Request does not match the API schema (unknown, missing, null or invalid field)", e))
		return false
	}
	if e = json.Unmarshal(b, out); e != nil {
		responses.Error(c, domain.Wrap("VALIDATION_ERROR", "Invalid request fields", e))
		return false
	}
	return true
}
func queryInt(c *gin.Context, key string, def int) (int, error) {
	raw, exists := c.GetQuery(key)
	if !exists {
		if _, ok := c.Request.URL.Query()[key]; ok {
			return 0, domain.Invalid("Empty " + key)
		}
		return def, nil
	}
	v, e := strconv.Atoi(raw)
	if e != nil {
		return 0, domain.Invalid("Invalid " + key)
	}
	return v, nil
}
func checkQuery(c *gin.Context, allowed ...string) error {
	q, e := c.Request.URL.Query(), error(nil)
	for k, v := range q {
		ok := false
		for _, a := range allowed {
			if k == a {
				ok = true
			}
		}
		if !ok || len(v) != 1 {
			return domain.Err("INVALID_CURSOR", "Unknown or repeated query parameter")
		}
	}
	return e
}
func listFilter(c *gin.Context, forecasts bool) (domain.ListFilter, error) {
	allowed := []string{"limit", "cursor"}
	if forecasts {
		allowed = append(allowed, "forecast_origin_from", "forecast_origin_to", "turbine_id", "status", "data_mode")
	}
	if e := checkQuery(c, allowed...); e != nil {
		return domain.ListFilter{}, e
	}
	f := domain.ListFilter{Status: c.Query("status"), DataMode: c.Query("data_mode"), Cursor: c.Query("cursor")}
	var e error
	f.Limit, e = queryInt(c, "limit", 25)
	if e != nil {
		return f, e
	}
	f.TurbineID, e = queryInt(c, "turbine_id", 0)
	if e != nil {
		return f, e
	}
	for key, dst := range map[string]**time.Time{"forecast_origin_from": &f.From, "forecast_origin_to": &f.To} {
		if raw, ok := c.Request.URL.Query()[key]; ok {
			t, err := time.Parse(time.RFC3339Nano, raw[0])
			if err != nil {
				return f, domain.Invalid("Date filters require RFC3339 with offset")
			}
			t = t.UTC()
			*dst = &t
		}
	}
	return f, f.Validate()
}
func eventQuery(c *gin.Context) (int64, int, error) {
	if e := checkQuery(c, "after", "limit"); e != nil {
		return 0, 0, e
	}
	after := int64(0)
	if vals, ok := c.Request.URL.Query()["after"]; ok {
		v, e := strconv.ParseInt(vals[0], 10, 64)
		if e != nil || v < 0 || v > 9007199254740991 {
			return 0, 0, domain.Err("INVALID_CURSOR", "Invalid after cursor")
		}
		after = v
	}
	limit, e := queryInt(c, "limit", 100)
	if e != nil || limit < 1 || limit > 1000 {
		return 0, 0, domain.Err("INVALID_CURSOR", "limit must be 1..1000")
	}
	return after, limit, nil
}
