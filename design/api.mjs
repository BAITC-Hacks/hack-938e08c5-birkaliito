export class ApiError extends Error {
  constructor(status, detail) {
    super(detail?.message || `HTTP ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

const url = (path, query = {}) => {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value !== undefined && value !== '' && value !== 'all') params.set(key, value);
  }
  return path + (params.size ? `?${params}` : '');
};

async function request(path, options = {}, query) {
  const response = await fetch(url(path, query), options);
  if (!response.ok) {
    let detail;
    try { detail = await response.json(); } catch { detail = {message:`HTTP ${response.status}`}; }
    throw new ApiError(response.status, detail);
  }
  return response;
}

const json = async (path, options, query) => (await request(path, options, query)).json();
const post = (path, body, key) => json(path, {
  method:'POST',
  headers:{'Content-Type':'application/json', ...(key ? {'Idempotency-Key':key} : {})},
  body:body === undefined ? undefined : JSON.stringify(body),
});

export const api = {
  meta:()=>json('/api/meta'),
  turbines:()=>json('/api/turbines'),
  models:()=>json('/api/models'),
  forecasts:(query={})=>json('/api/forecast-runs',{},query),
  createForecast:(body,key)=>post('/api/forecast-runs',body,key),
  forecastDetails:id=>json(`/api/forecast-runs/${encodeURIComponent(id)}`),
  job:id=>json(`/api/jobs/${encodeURIComponent(id)}`),
  events:(id,after=0)=>json(`/api/jobs/${encodeURIComponent(id)}/events`,{}, {after,limit:1000}),
  result:id=>json(`/api/forecast-runs/${encodeURIComponent(id)}/result`),
  cancel:id=>post(`/api/jobs/${encodeURIComponent(id)}/cancel`),
  createReplay:(body,key)=>post('/api/replays',body,key),
  replayDetails:id=>json(`/api/replays/${encodeURIComponent(id)}`),
  replayRuns:id=>json(`/api/replays/${encodeURIComponent(id)}/runs`),
  weather:id=>json(`/api/forecast-runs/${encodeURIComponent(id)}/weather`),
  explanation:id=>json(`/api/forecast-runs/${encodeURIComponent(id)}/explanation`),
  evaluations:(query={})=>json('/api/evaluations',{},query),
  dataQuality:()=>json('/api/data-quality'),
  exportForecast:async id=>(await request(`/api/forecast-runs/${encodeURIComponent(id)}/export`)).blob(),
  exportReplay:async(id,allowPartial=false)=>{
    const response=await request(`/api/replays/${encodeURIComponent(id)}/export`,{}, {allow_partial:allowPartial});
    return {
      blob:await response.blob(),
      status:response.headers.get('X-Replay-Export-Status'),
      total:Number(response.headers.get('X-Replay-Total')),
      completed:Number(response.headers.get('X-Replay-Completed')),
      failed:Number(response.headers.get('X-Replay-Failed')),
      cancelled:Number(response.headers.get('X-Replay-Cancelled')),
    };
  },
};

export const historyRun = item => ({
  key:item.job.job_id,
  origin:item.request.forecast_origin,
  horizon:item.request.horizon_hours,
  turbines:item.request.turbine_ids.map(String),
  stage:item.cancel_requested && item.job.status === 'running' ? 'cancel_requested' : item.job.status,
  quality:'passed',
  explanation:'unavailable',
  executedAt:item.job.updated_at,
  model:item.request.model_version,
  mode:item.request.data_mode,
  points:[],
  remote:true,
});

export const attachResult = (run, result) => Object.assign(run, {
  key:result.run_id,
  origin:result.forecast_origin,
  horizon:result.horizon_hours,
  turbines:(result.turbine_ids||[...new Set(result.points.map(point=>point.turbine_id))]).map(String),
  points:result.points.map(point=>({...point,turbine_id:String(point.turbine_id)})),
  model:result.model_version,
  mode:result.data_mode,
  featureVersion:result.feature_version,
  trainingDataAvailableThrough:result.training_data_available_through,
  explanation:result.explanation_status,
  explanationText:result.explanation,
  quality:result.quality_status || 'passed',
  warnings:result.warnings||[],
  weatherRuns:result.weather_runs||[],
});

export const waitForJob = (id, onJob=()=>{}) => new Promise((resolve, reject) => {
  let source;
  let stopped=false;
  let polling=false;
  const finish=async()=>{
    if(stopped)return;
    try {
      const job=await api.job(id);onJob(job);
      if(['completed','failed','cancelled'].includes(job.status)){stopped=true;source?.close();resolve(job);return;}
    } catch(error){if(stopped)return;stopped=true;source?.close();reject(error);return;}
    setTimeout(finish,1000);
  };
  const poll=()=>{if(polling||stopped)return;polling=true;source?.close();void finish();};
  if(typeof EventSource!=='undefined'){
    source=new EventSource(`/api/jobs/${encodeURIComponent(id)}/stream`);
    source.addEventListener('agent_event',event=>{try{const data=JSON.parse(event.data);onJob({status:data.status||'running',stage:data.node});}catch{}});
    source.addEventListener('stream_end',poll);
    source.addEventListener('stream_error',poll);
    source.onerror=poll;
  } else poll();
});

export async function waitForForecast(id,onJob) {
  const job=await waitForJob(id,onJob);
  if(job.status!=='completed')throw new ApiError(409,{message:job.error_message||`Задание ${job.status}`});
  return api.result(id);
}

export async function downloadBlob(blob, name) {
  const objectURL=URL.createObjectURL(blob);
  const anchor=document.createElement('a');anchor.href=objectURL;anchor.download=name;anchor.click();
  setTimeout(()=>URL.revokeObjectURL(objectURL),2000);
}
