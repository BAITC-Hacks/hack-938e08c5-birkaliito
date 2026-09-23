"""Generate boundary types and canonical OpenAPI. Standard library only; not ML code."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
S = {}
def string(**kw): return dict(type="string", **kw)
def enum(*values): return dict(type="string", enum=list(values))
def integer(**kw): return dict(type="integer", **kw)
def number(**kw): return dict(type="number", **kw)
def ref(name): return {"$ref": f"#/components/schemas/{name}"}
def array(item, **kw): return dict(type="array", items=item, **kw)
def nullable(item): return {"anyOf": [item, {"type": "null"}]}
def obj(name, fields, optional=()):
    S[name] = dict(type="object", additionalProperties=False, properties=fields,
                   required=[k for k in fields if k not in optional])
    return ref(name)
ts = string(format="date-time")
boolean = dict(type="boolean")
ident = string(pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")
mode = enum("real", "fixture")
status = enum("queued", "running", "completed", "failed", "cancelled")
turbine = integer(enum=[1, 2])
turbines = array(turbine, minItems=1, maxItems=2, uniqueItems=True, default=[1, 2])
horizon = integer(enum=[24, 48], default=48)
request = dict(forecast_origin=ts, horizon_hours=horizon, turbine_ids=turbines,
               model_version=string(minLength=1, maxLength=128),
               mode=dict(enum("replay", "live"), default="replay"), data_mode=dict(mode, default="real"))
obj("ForecastRequest", request, ("horizon_hours", "turbine_ids", "mode", "data_mode"))
obj("ReplayRequest", dict(origins=array(ts,minItems=1,maxItems=366,uniqueItems=True),
    **{k:v for k,v in request.items() if k not in ("forecast_origin", "mode")}),
    ("horizon_hours", "turbine_ids", "data_mode"))
obj("JobRecord", dict(job_id=ident,job_type=enum("forecast","replay"),status=status,created_at=ts,
    updated_at=ts,stage=string(minLength=1),error_code=nullable(string()),error_message=nullable(string())))
obj("ForecastPoint",dict(turbine_id=turbine,valid_time=ts,interval_end=ts,lead_hours=integer(minimum=1,maximum=48),
    power_mean=number(),q10=number(),q50=number(),q90=number()))
obj("WeatherProvenance",dict(provider=enum("GFS"),run_id=string(minLength=1),initialization_time=ts,
    effective_available_at=ts,availability_basis=enum("observed_publication","conservative_policy"),
    availability_policy_id=nullable(string()),retrieved_at=ts,source_reference=string(minLength=1),
    content_sha256=string(pattern="^[a-f0-9]{64}$")))
obj("ForecastResult",dict(run_id=ident,forecast_origin=ts,horizon_hours=horizon,turbine_ids=turbines,
    data_mode=mode,model_version=string(minLength=1),feature_version=string(minLength=1),
    training_data_available_through=ts,quality_status=enum("passed","degraded"),
    explanation_status=enum("llm","template","unavailable"),explanation=string(),warnings=array(string()),
    weather_runs=array(ref("WeatherProvenance"),minItems=1),points=array(ref("ForecastPoint"),minItems=24,maxItems=96)))
obj("AgentEvent",dict(event_id=integer(minimum=1,maximum=9007199254740991),job_id=ident,recorded_at=ts,
    kind=enum("started","tool_requested","tool_completed","policy_rejected","warning","completed","failed"),
    node=string(),message=string(),evidence_refs=array(string())))
obj("ApiError",dict(code=string(),message=string(),request_id=nullable(string())))
obj("Capabilities",{k:boolean for k in ("forecast","replay","cancel","sse","weather_details","shap","evaluations","data_quality","simulated")})
obj("Meta",dict(service=string(),version=string(),contract_version=string(),agent_mode=enum("mock","http"),
    allowed_data_modes=array(mode),display_timezone=string(),source_timezone_status=enum("unconfirmed","confirmed"),
    target_unit=enum("normalized_power"),normalization_status=enum("unconfirmed","confirmed"),
    agent_dependency=enum("available","unavailable"),capabilities=ref("Capabilities")))
obj("Turbine",dict(id=turbine,name=string(),latitude=number(minimum=-90,maximum=90),longitude=number(minimum=-180,maximum=180),
    rated_power_mw=nullable(number(exclusiveMinimum=0)),hub_height_m=nullable(number(exclusiveMinimum=0)),metadata_status=enum("configured_unverified","verified")))
obj("Model",dict(model_version=string(minLength=1),display_name=string(),data_mode=mode,feature_version=string(),
    training_data_available_through=ts,supports_quantiles=boolean,availability=enum("ready","unavailable")))
obj("ForecastRunDetails",dict(job=ref("JobRecord"),request=ref("ForecastRequest"),parent_replay_id=nullable(ident),
    result_available=boolean,cancel_requested=boolean))
obj("ReplayCounters",{k:integer(minimum=0) for k in ("total","queued","running","completed","failed","cancelled")})
obj("ReplayDetails",dict(job=ref("JobRecord"),request=ref("ReplayRequest"),cancel_requested=boolean,
    counters=ref("ReplayCounters"),has_failures=boolean))
obj("WeatherPoint",dict(turbine_id=turbine,valid_time=ts,wind_speed_ms=nullable(number()),wind_height_m=nullable(number()),
    temperature_c=nullable(number()),is_interpolated=boolean))
obj("WeatherDetails",dict(run_id=ident,data_mode=mode,status=enum("available","unavailable"),
    weather_runs=array(ref("WeatherProvenance")),points=array(ref("WeatherPoint"))))
obj("FeatureContribution",dict(feature=string(),value=number(),contribution=number()))
obj("SHAPItem",dict(turbine_id=turbine,valid_time=ts,output=enum("power_mean"),base_value=number(),prediction=number(),
    feature_contributions=array(ref("FeatureContribution")),output_unit=enum("normalized_power")))
obj("ExplanationDetails",dict(run_id=ident,data_mode=mode,status=enum("llm","template","unavailable"),text=string(),
    shap_status=enum("available","unavailable"),shap_items=array(ref("SHAPItem"))))
obj("EvaluationMetric",dict(turbine_id=turbine,lead_from=integer(minimum=1,maximum=48),lead_to=integer(minimum=1,maximum=48),
    mae=nullable(number(minimum=0)),rmse=nullable(number(minimum=0)),bias=nullable(number()),
    coverage_q10_q90=nullable(number(minimum=0,maximum=1)),mean_interval_width=nullable(number(minimum=0))))
obj("EvaluationReport",dict(evaluation_id=ident,data_mode=mode,status=enum("available","unavailable"),model_version=string(),
    baseline_name=string(),target_unit=enum("normalized_power"),evaluation_scope=enum("end_to_end","power_conversion_only"),
    period_start=ts,period_end=ts,training_data_available_through=ts,n_observations=nullable(integer(minimum=0)),
    metrics=array(ref("EvaluationMetric")),notes=array(string())))
obj("TurbineQuality",dict(turbine_id=turbine,range_start=nullable(ts),range_end=nullable(ts),row_count=nullable(integer(minimum=0)),
    complete_hour_count=nullable(integer(minimum=0)),missing_hour_count=nullable(integer(minimum=0)),warnings=array(string())))
obj("DataQualityReport",dict(status=enum("available","unavailable"),generated_at=nullable(ts),data_mode=mode,
    source_reference=nullable(string()),turbines=array(ref("TurbineQuality"))))
for name,item in (("TurbineList","Turbine"),("ModelList","Model"),("ForecastList","ForecastRunDetails"),("EvaluationList","EvaluationReport")):
    obj(name,dict(items=array(ref(item)),next_cursor=nullable(string())))
obj("Health",dict(status=enum("ok")))
obj("StreamEnd",dict(job_id=ident,status=status))

paths={}
errors={400:"Malformed input",403:"FIXTURE_MODE_DISABLED",404:"Not found",409:"Conflict or result not ready",410:"EVENT_CURSOR_EXPIRED",413:"Body too large",415:"Content type unsupported",422:"Invalid parameters",429:"Rate limited",500:"Internal error",501:"FEATURE_NOT_SUPPORTED",502:"UPSTREAM_CONTRACT_VIOLATION",503:"Dependency or queue unavailable",504:"Upstream timeout"}
def param(name,schema,where="query",required=False):return dict(name=name,**{"in":where},required=required,schema=schema)
def route(method,path,response,code=200,body=None,params=(),media="application/json"):
    pp=list(params)
    if "{id}" in path:pp.insert(0,param("id",ident,"path",True))
    op=dict(operationId=method+"_"+path.strip("/").replace("/","_").replace("{id}","id").replace("-","_"),parameters=pp,
        responses={str(code):dict(description="Accepted job (mock is volatile)" if code==202 else "Success",content={media:dict(schema=ref(response) if isinstance(response,str) else response)})})
    if body:
        op["requestBody"]=dict(required=True,content={"application/json":dict(schema=ref(body))})
        pp.append(param("Idempotency-Key",string(minLength=1,maxLength=128,pattern=r"^[\x21-\x7e]+$"),"header",True))
    for c,d in errors.items():op["responses"][str(c)]=dict(description=d,content={"application/json":dict(schema=ref("ApiError"))})
    paths.setdefault(path,{})[method]=op
route("get","/healthz","Health");route("get","/readyz","Health")
route("get","/openapi.yaml",string(),media="application/yaml");route("get","/docs",string(),media="text/html")
for suffix,name in (("meta","Meta"),("turbines","TurbineList"),("models","ModelList"),("evaluations","EvaluationList"),("data-quality","DataQualityReport")):
    route("get","/api/"+suffix,name)
route("get","/api/evaluations/{id}","EvaluationReport")
route("post","/api/forecast-runs","JobRecord",202,"ForecastRequest")
route("post","/api/replays","JobRecord",202,"ReplayRequest")
page=[param("limit",integer(minimum=1,maximum=100,default=25)),param("cursor",string())]
paths["/api/evaluations"]["get"]["parameters"]=page
filters=[param("forecast_origin_from",ts),param("forecast_origin_to",ts),param("turbine_id",turbine),param("status",status),param("data_mode",mode)]+page
route("get","/api/forecast-runs","ForecastList",params=filters)
route("get","/api/forecast-runs/{id}","ForecastRunDetails")
for suffix,name in (("result","ForecastResult"),("weather","WeatherDetails"),("explanation","ExplanationDetails")):
    route("get","/api/forecast-runs/{id}/"+suffix,name)
route("get","/api/jobs/{id}","JobRecord")
route("post","/api/jobs/{id}/cancel","JobRecord",202)
paths["/api/jobs/{id}/cancel"]["post"]["responses"]["200"]=dict(description="Already cancelled",content={"application/json":dict(schema=ref("JobRecord"))})
eventparams=[param("after",integer(minimum=0,maximum=9007199254740991,default=0)),param("limit",integer(minimum=1,maximum=1000,default=100))]
route("get","/api/jobs/{id}/events",array(ref("AgentEvent")),params=eventparams)
route("get","/api/jobs/{id}/stream",string(),params=eventparams+[param("Last-Event-ID",string(pattern="^[0-9]+$"),"header")],media="text/event-stream")
paths["/api/jobs/{id}/stream"]["get"]["description"]="agent_event with monotonically increasing id; heartbeat comments; stream_end (StreamEnd) or stream_error (ApiError) have no id. Close on stream_end. Resume with Last-Event-ID (priority over after). Both cursors validated."
route("get","/api/replays/{id}","ReplayDetails")
route("get","/api/replays/{id}/runs",array(ref("JobRecord")))
route("get","/api/forecast-runs/{id}/export",string(),media="text/csv")
route("get","/api/replays/{id}/export",string(),params=[param("allow_partial",dict(type="boolean",default=False))],media="text/csv")
paths["/api/replays/{id}/export"]["get"]["responses"]["200"]["headers"]={k:dict(description="Replay snapshot",schema=string()) for k in ("X-Replay-Export-Status","X-Replay-Total","X-Replay-Completed","X-Replay-Failed","X-Replay-Cancelled","Content-Disposition")}
doc=dict(openapi="3.1.0",info=dict(title="Wind Forecast API",version="1.1.0",description="All output timestamps UTC. lead=1..H; valid_time=origin+lead hours; interval_end=valid_time+1 hour. Normalization and SCADA timezone unconfirmed. Mock is explicitly fixture and volatile. Whole-hour alignment is checked after UTC normalization. Cross-field invariants are checked by domain validation. Forecast IDs equal job IDs; replay IDs equal job IDs."),paths=paths,components=dict(schemas=S))
(ROOT/"api").mkdir(parents=True,exist_ok=True)
(ROOT/"api/openapi.yaml").write_text(json.dumps(doc,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

initialisms={"id":"ID","ids":"IDs","url":"URL","mw":"MW","ms":"MS","sha256":"SHA256","shap":"SHAP","sse":"SSE","mae":"MAE","rmse":"RMSE","llm":"LLM","api":"API"}
def fieldname(n):return "".join(initialisms.get(p,p[:1].upper()+p[1:]) for p in n.split("_"))
def gotype(s):
    if "$ref" in s:return s["$ref"].split("/")[-1]
    if "anyOf" in s:return "*"+gotype(s["anyOf"][0])
    if s.get("format")=="date-time":return "time.Time"
    return {"string":lambda:"string","integer":lambda:"int64" if s.get("maximum")==9007199254740991 else "int","number":lambda:"float64","boolean":lambda:"bool","array":lambda:"[]"+gotype(s["items"])}[s["type"]]()
def tstype(s):
    if "$ref" in s:return s["$ref"].split("/")[-1]
    if "anyOf" in s:return tstype(s["anyOf"][0])+" | null"
    if "enum" in s:return " | ".join(json.dumps(v) for v in s["enum"])
    if s["type"]=="array":return "Array<"+tstype(s["items"])+">"
    return {"string":"string","integer":"number","number":"number","boolean":"boolean"}[s["type"]]
for package,path,tags in (("domain","internal/domain/types_generated.go",False),("dto","internal/transport/http/dto/types_generated.go",True),("agenthttp","internal/adapters/agenthttp/types_generated.go",True)):
    code=f'// Code generated by tools/generate_contract.py; DO NOT EDIT.\npackage {package}\n\nimport "time"\n\n'
    for name,schema in S.items():
        code+=f'type {name} struct {{\n'
        for key,s in schema["properties"].items():
            code+=f' {fieldname(key)} {gotype(s)}'+(f' `json:"{key}"`' if tags else "")+"\n"
        code+='}\n\n'
    p=ROOT/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(code,encoding="utf-8")
    if tags:
        code=f'// Code generated by tools/generate_contract.py; DO NOT EDIT.\npackage {package}\nimport "wind/backend/internal/domain"\n'
        # Explicit boundary conversion generated from the one schema. No reflection or JSON roundtrip in domain.
        for name,schema in S.items():
            for direction in ("FromDomain","ToDomain"):
                src,dst=("domain.","") if direction=="FromDomain" else ("","domain.")
                code+=f'func {name}{direction}(v {src}{name}) {dst}{name} {{\n out := {dst}{name}{{}}\n'
                for key,s in schema["properties"].items():
                    f=fieldname(key)
                    if "$ref" in s:code+=f' out.{f} = {gotype(s)}{direction}(v.{f})\n'
                    elif s.get("type")=="array":
                        item=s["items"];typ=gotype(item); target=dst+typ if "$ref" in item else typ
                        code+=f' out.{f} = make([]{target}, len(v.{f}))\n for i, item := range v.{f} {{ '
                        code+=f'out.{f}[i] = {typ}{direction}(item)' if "$ref" in item else f'out.{f}[i] = item'
                        code+=' }\n'
                    elif "anyOf" in s:code+=f' if v.{f} != nil {{ item := *v.{f}; out.{f} = &item }}\n'
                    else:code+=f' out.{f} = v.{f}\n'
                code+=' return out\n}\n'
        (p.parent/"mapping_generated.go").write_text(code,encoding="utf-8")
typescript='// Generated from the canonical contract. Timestamps are RFC3339; output UTC.\n'
for name,schema in S.items():
    typescript+=f'export interface {name} {{\n'
    for key,s in schema["properties"].items():typescript+=f'  {key}'+("?" if key not in schema["required"] else "")+f': {tstype(s)};\n'
    typescript+='}\n'
p=ROOT/"contracts/typescript/api-types.ts";p.parent.mkdir(parents=True,exist_ok=True);p.write_text(typescript,encoding="utf-8")
