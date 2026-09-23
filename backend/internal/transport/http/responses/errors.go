package responses

import (
	"context"
	"errors"
	"github.com/gin-gonic/gin"
	"net/http"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
)

func Error(c *gin.Context, err error) {
	code, msg, status := "INTERNAL_ERROR", "Unexpected internal error", http.StatusInternalServerError
	var e *domain.Error
	if errors.As(err, &e) {
		code, msg = e.Code, e.Message
		switch code {
		case "BAD_JSON", "INVALID_CURSOR", "INVALID_REQUEST_ID":
			status = 400
		case "FIXTURE_MODE_DISABLED":
			status = 403
		case "NOT_FOUND":
			status = 404
		case "IDEMPOTENCY_CONFLICT", "RESULT_NOT_READY", "JOB_NOT_CANCELLABLE", "REPLAY_INCOMPLETE":
			status = 409
		case "EVENT_CURSOR_EXPIRED":
			status = 410
		case "BODY_TOO_LARGE":
			status = 413
		case "UNSUPPORTED_MEDIA_TYPE":
			status = 415
		case "VALIDATION_ERROR", "DATA_MODE_MISMATCH":
			status = 422
		case "RATE_LIMITED":
			status = 429
		case "FEATURE_NOT_SUPPORTED":
			status = 501
		case "UPSTREAM_CONTRACT_VIOLATION":
			status = 502
		case "DEPENDENCY_UNAVAILABLE", "QUEUE_FULL":
			status = 503
		case "UPSTREAM_TIMEOUT":
			status = 504
		}
	}
	if errors.Is(err, context.DeadlineExceeded) {
		code, msg, status = "UPSTREAM_TIMEOUT", "Dependency deadline exceeded", 504
	}
	id := c.GetString("request_id")
	_ = c.Error(err)
	c.Set("error_code", code)
	c.AbortWithStatusJSON(status, dto.ApiError{Code: code, Message: msg, RequestID: &id})
}
