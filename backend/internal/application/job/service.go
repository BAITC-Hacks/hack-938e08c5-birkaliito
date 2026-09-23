package job

import("context";"wind/backend/internal/domain";"wind/backend/internal/application/ports")
type Service struct{jobs ports.JobGateway;events ports.EventReader;catalog ports.ModelCatalog}
func NewJobService(j ports.JobGateway,e ports.EventReader,c ports.ModelCatalog)*Service{return &Service{j,e,c}}
func(s *Service) Get(ctx context.Context,id string)(domain.JobRecord,error){j,e:=s.jobs.GetJob(ctx,id);if e==nil{e=domain.ValidateJob(j);if j.JobID!=id{e=domain.Violation("wrong job id")}};return j,e}
func(s *Service) Events(ctx context.Context,id string,after int64,limit int)([]domain.AgentEvent,error){if after<0||after>9007199254740991||limit<1||limit>1000{return nil,domain.Err("INVALID_CURSOR","Invalid event cursor or limit")};v,e:=s.events.Events(ctx,id,after,limit);if e==nil{e=domain.ValidateEvents(v,id,after)};return v,e}
func(s *Service) Cancel(ctx context.Context,id string)(domain.JobRecord,error){c,e:=s.catalog.Capabilities(ctx);if e!=nil{return domain.JobRecord{},e};if !c.Cancel{return domain.JobRecord{},domain.Err("FEATURE_NOT_SUPPORTED","Cancellation unsupported")};return s.jobs.Cancel(ctx,id)}
