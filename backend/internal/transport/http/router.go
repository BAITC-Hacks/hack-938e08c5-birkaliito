package httptransport

import (
	"github.com/gin-gonic/gin"
	"log/slog"
	"wind/backend/api"
	"wind/backend/internal/domain"
	"wind/backend/internal/transport/http/dto"
	"wind/backend/internal/transport/http/handlers"
	"wind/backend/internal/transport/http/middleware"
	"wind/backend/internal/transport/http/responses"
)

func NewRouter(f *handlers.ForecastHandler, j *handlers.JobHandler, r *handlers.ReplayHandler, c *handlers.CatalogHandler, e *handlers.EvaluationHandler, log *slog.Logger, origins []string) *gin.Engine {
	router := gin.New()
	_ = router.SetTrustedProxies(nil)
	router.Use(middleware.Common(log, origins))
	router.HandleMethodNotAllowed = true
	router.GET("/healthz", func(c *gin.Context) { c.JSON(200, dto.Health{Status: "ok"}) })
	router.GET("/readyz", c.Ready)
	router.GET("/openapi.yaml", func(c *gin.Context) { c.Data(200, "application/yaml; charset=utf-8", api.Spec) })
	router.GET("/docs", func(c *gin.Context) { c.Data(200, "text/html; charset=utf-8", api.Docs) })
	router.GET("/api/meta", c.Meta)
	router.GET("/api/turbines", c.Turbines)
	router.GET("/api/models", c.Models)
	router.POST("/api/forecast-runs", f.Create)
	router.GET("/api/forecast-runs", f.List)
	router.GET("/api/forecast-runs/:id", f.Details)
	router.GET("/api/forecast-runs/:id/result", f.Result)
	router.GET("/api/forecast-runs/:id/export", f.Export)
	router.GET("/api/forecast-runs/:id/weather", f.Weather)
	router.GET("/api/forecast-runs/:id/explanation", f.Explanation)
	router.GET("/api/jobs/:id", j.Get)
	router.GET("/api/jobs/:id/events", j.Events)
	router.GET("/api/jobs/:id/stream", j.Stream)
	router.POST("/api/jobs/:id/cancel", j.Cancel)
	router.POST("/api/replays", r.Create)
	router.GET("/api/replays/:id", r.Details)
	router.GET("/api/replays/:id/runs", r.Runs)
	router.GET("/api/replays/:id/export", r.Export)
	router.GET("/api/evaluations", e.List)
	router.GET("/api/evaluations/:id", e.Get)
	router.GET("/api/data-quality", e.Quality)
	router.NoRoute(func(c *gin.Context) { responses.Error(c, domain.Err("NOT_FOUND", "Route not found")) })
	router.NoMethod(func(c *gin.Context) { responses.Error(c, domain.Err("NOT_FOUND", "Route or method not found")) })
	return router
}
