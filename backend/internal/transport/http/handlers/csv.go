package handlers

import (
	"encoding/csv"
	"github.com/gin-gonic/gin"
	"net/http"
	"slices"
	"sort"
	"strconv"
	"time"
	"wind/backend/internal/domain"
)

func writeCSV(c *gin.Context, results []domain.ForecastResult, id string) {
	c.Header("Content-Type", "text/csv; charset=utf-8")
	c.Header("Content-Disposition", `attachment; filename="`+id+`.csv"`)
	c.Status(http.StatusOK)
	w := csv.NewWriter(c.Writer)
	_ = w.Write([]string{"run_id", "forecast_origin", "turbine_id", "valid_time", "interval_end", "lead_hours", "power_mean", "q10", "q50", "q90", "data_mode"})
	for _, r := range results {
		points := slices.Clone(r.Points)
		sort.Slice(points, func(i, j int) bool {
			if points[i].TurbineID == points[j].TurbineID {
				return points[i].LeadHours < points[j].LeadHours
			}
			return points[i].TurbineID < points[j].TurbineID
		})
		for _, p := range points {
			row := []string{r.RunID, r.ForecastOrigin.UTC().Format(time.RFC3339), strconv.Itoa(p.TurbineID), p.ValidTime.UTC().Format(time.RFC3339), p.IntervalEnd.UTC().Format(time.RFC3339), strconv.Itoa(p.LeadHours)}
			for _, n := range []float64{p.PowerMean, p.Q10} {
				row = append(row, strconv.FormatFloat(n, 'g', -1, 64))
			}
			if p.Q50 == nil {
				row = append(row, "")
			} else {
				row = append(row, strconv.FormatFloat(*p.Q50, 'g', -1, 64))
			}
			row = append(row, strconv.FormatFloat(p.Q90, 'g', -1, 64))
			row = append(row, r.DataMode)
			if e := w.Write(row); e != nil {
				_ = c.Error(e)
				return
			}
		}
	}
	w.Flush()
	if e := w.Error(); e != nil {
		_ = c.Error(e)
	}
}
