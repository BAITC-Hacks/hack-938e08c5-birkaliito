package ports

import("context";"time";"wind/backend/internal/domain")
type Clock interface {Now()time.Time;Wait(context.Context,time.Duration)error}
type ForecastGateway interface {
 CreateForecast(context.Context,domain.ForecastRequest,domain.Operation)(domain.JobRecord,error)
 ForecastDetails(context.Context,string)(domain.ForecastRunDetails,error)
 ForecastResult(context.Context,string)(domain.ForecastResult,error)
 ListForecasts(context.Context,domain.ListFilter)(domain.ForecastList,error)
 Explanation(context.Context,string)(domain.ExplanationDetails,error)
}
type JobGateway interface {GetJob(context.Context,string)(domain.JobRecord,error);Cancel(context.Context,string)(domain.JobRecord,error)}
type EventReader interface {Events(context.Context,string,int64,int)([]domain.AgentEvent,error)}
type ReplayGateway interface {
 CreateReplay(context.Context,domain.ReplayRequest,domain.Operation)(domain.JobRecord,error)
 ReplayDetails(context.Context,string)(domain.ReplayDetails,error)
 ReplayRuns(context.Context,string)([]domain.JobRecord,error)
}
type ModelCatalog interface {Models(context.Context)(domain.ModelList,error);Capabilities(context.Context)(domain.Capabilities,error);Ready(context.Context)error}
type EvaluationReader interface{Evaluations(context.Context,domain.ListFilter)(domain.EvaluationList,error);Evaluation(context.Context,string)(domain.EvaluationReport,error);DataQuality(context.Context)(domain.DataQualityReport,error)}
type WeatherReader interface{Weather(context.Context,string)(domain.WeatherDetails,error)}
type TurbineRepository interface{Turbines(context.Context)(domain.TurbineList,error)}
