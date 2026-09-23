package replay

import("context";"wind/backend/internal/domain";"wind/backend/internal/application/ports";"wind/backend/internal/application/forecast")
type Service struct{gateway ports.ReplayGateway;forecast *forecast.Service;catalog ports.ModelCatalog}
func NewReplayService(g ports.ReplayGateway,f *forecast.Service,c ports.ModelCatalog)*Service{return &Service{g,f,c}}
func(s *Service) Create(ctx context.Context,r domain.ReplayRequest,op domain.Operation)(domain.JobRecord,error){
 r,e:=domain.NormalizeReplay(r);if e!=nil{return domain.JobRecord{},e};if e=domain.ValidateKey(op.IdempotencyKey);e!=nil{return domain.JobRecord{},e}
 cap,e:=s.catalog.Capabilities(ctx);if e!=nil{return domain.JobRecord{},e};if !cap.Replay{return domain.JobRecord{},domain.Err("FEATURE_NOT_SUPPORTED","Replay unsupported")}
 for _,t:=range r.Origins{if e=s.forecast.CheckRequest(ctx,domain.ForecastRequest{ForecastOrigin:t,HorizonHours:r.HorizonHours,TurbineIDs:r.TurbineIDs,ModelVersion:r.ModelVersion,Mode:"replay",DataMode:r.DataMode});e!=nil{return domain.JobRecord{},e}}
 return s.gateway.CreateReplay(ctx,r,op)
}
func(s *Service) Details(ctx context.Context,id string)(domain.ReplayDetails,error){return s.gateway.ReplayDetails(ctx,id)}
func(s *Service) Runs(ctx context.Context,id string)([]domain.JobRecord,error){return s.gateway.ReplayRuns(ctx,id)}
func(s *Service) Export(ctx context.Context,id string,allowPartial bool)(domain.Export,error){
 d,e:=s.gateway.ReplayDetails(ctx,id);if e!=nil{return domain.Export{},e}
 if !domain.Terminal(d.Job.Status)||(!allowPartial&&d.Job.Status!="completed"){return domain.Export{},domain.Err("REPLAY_INCOMPLETE","Replay export requires a terminal snapshot; failed/cancelled children require allow_partial=true")}
 jobs,e:=s.gateway.ReplayRuns(ctx,id);if e!=nil{return domain.Export{},e}
 out:=domain.Export{Results:[]domain.ForecastResult{},Counters:d.Counters,Partial:d.Job.Status!="completed"}
 for _,j:=range jobs{if j.Status=="completed"{r,e:=s.forecast.Result(ctx,j.JobID);if e!=nil{return domain.Export{},e};out.Results=append(out.Results,r)}}
 return out,nil
}
