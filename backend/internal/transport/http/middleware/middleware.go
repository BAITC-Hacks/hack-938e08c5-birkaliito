package middleware

import (
	"crypto/rand"
	"encoding/hex"
	"fmt"
	"github.com/gin-gonic/gin"
	"log/slog"
	"strings"
	"time"
	"wind/backend/internal/application/ports"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/responses"
)

func Common(log *slog.Logger, origins []string) gin.HandlerFunc {
	return func(c *gin.Context) {
		start := time.Now()
		b := make([]byte, 12)
		_, _ = rand.Read(b)
		id := "req-" + hex.EncodeToString(b)
		given := c.GetHeader("X-Request-ID")
		if given != "" && domain.ValidID(given) {
			id = given
		}
		c.Set("request_id", id)
		c.Header("X-Request-ID", id)
		c.Request = c.Request.WithContext(ports.WithRequestID(c.Request.Context(), id))
		defer func() {
			if v := recover(); v != nil {
				log.Error("request panic", "request_id", id, "panic", fmt.Sprint(v))
				if !c.Writer.Written() {
					responses.Error(c, domain.Err("INTERNAL_ERROR", "Unexpected internal error"))
				}
				c.Abort()
			}
			args := []any{"request_id", id, "job_id", c.Param("id"), "route", c.FullPath(), "status", c.Writer.Status(), "duration_ms", time.Since(start).Milliseconds(), "dependency", "agent", "error_code", c.GetString("error_code")}
			if len(c.Errors) > 0 {
				args = append(args, "error", c.Errors.Last().Err)
			}
			log.Info("http request", args...)
		}()
		if given != "" && !domain.ValidID(given) {
			responses.Error(c, domain.Err("INVALID_REQUEST_ID", "Invalid X-Request-ID"))
			return
		}
		origin := c.GetHeader("Origin")
		if origin != "" {
			allowed := false
			for _, v := range origins {
				if v == origin {
					allowed = true
					break
				}
			}
			if allowed {
				c.Header("Access-Control-Allow-Origin", origin)
				c.Header("Vary", "Origin")
				c.Header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
				c.Header("Access-Control-Allow-Headers", "Content-Type, Idempotency-Key, Last-Event-ID, X-Request-ID")
				c.Header("Access-Control-Expose-Headers", "X-Request-ID, Content-Disposition, X-Replay-Export-Status, X-Replay-Total, X-Replay-Completed, X-Replay-Failed, X-Replay-Cancelled")
			} else if c.Request.Method == "OPTIONS" {
				c.AbortWithStatus(403)
				return
			}
		}
		if c.Request.Method == "OPTIONS" {
			c.AbortWithStatus(204)
			return
		}
		for _, p := range c.Params {
			if p.Key == "id" && !domain.ValidID(p.Value) {
				responses.Error(c, domain.Invalid("Invalid resource ID"))
				return
			}
		}
		if strings.Contains(c.Request.URL.RawQuery, ";") {
			responses.Error(c, domain.Err("BAD_JSON", "Invalid query"))
			return
		}
		c.Next()
	}
}
