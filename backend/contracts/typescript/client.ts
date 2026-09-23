import type { AgentEvent, ApiError, DataQualityReport, EvaluationList, EvaluationReport, ExplanationDetails, ForecastList, ForecastRequest, ForecastResult, ForecastRunDetails, JobRecord, Meta, ModelList, ReplayDetails, ReplayRequest, StreamEnd, TurbineList, WeatherDetails } from './api-types';

export class ApiException extends Error {
  constructor(public readonly status: number, public readonly detail: ApiError) { super(detail.message); }
}
export type Query = Record<string, string | number | boolean | undefined>;
export interface Subscription { close(): void }
export interface EventCallbacks {
  onEvent(event: AgentEvent): void;
  onEnd(event: StreamEnd): void;
  onError?(error: unknown): void;
}

/** Point baseURL at Go or a same-origin development proxy. Never send the Python token. */
export class WindClient {
  constructor(private readonly baseURL = '', private readonly pollMilliseconds = 1000) {}
  private url(path: string, query: Query = {}) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(query)) if (value !== undefined) params.set(key, String(value));
    return this.baseURL.replace(/\/$/, '') + path + (params.size ? '?' + params.toString() : '');
  }
  private async response(path: string, options: RequestInit = {}, query?: Query) {
    const response = await fetch(this.url(path, query), options);
    if (!response.ok) {
      let detail: ApiError;
      try { detail = await response.json() as ApiError; }
      catch { detail = { code: 'HTTP_ERROR', message: `HTTP ${response.status}`, request_id: response.headers.get('X-Request-ID') }; }
      throw new ApiException(response.status, detail);
    }
    return response;
  }
  private async get<T>(path: string, signal?: AbortSignal, query?: Query): Promise<T> { return (await this.response(path, { signal }, query)).json() as Promise<T>; }
  private async post<T>(path: string, body: unknown, key: string | undefined, signal?: AbortSignal): Promise<T> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    if (key) headers['Idempotency-Key'] = key;
    return (await this.response(path, { method: 'POST', headers, body: body === undefined ? undefined : JSON.stringify(body), signal })).json() as Promise<T>;
  }
  getMeta(signal?: AbortSignal) { return this.get<Meta>('/api/meta', signal); }
  listTurbines(signal?: AbortSignal) { return this.get<TurbineList>('/api/turbines', signal); }
  listModels(signal?: AbortSignal) { return this.get<ModelList>('/api/models', signal); }
  createForecast(request: ForecastRequest, idempotencyKey: string, signal?: AbortSignal) { return this.post<JobRecord>('/api/forecast-runs', request, idempotencyKey, signal); }
  listForecasts(query: Query = {}, signal?: AbortSignal) { return this.get<ForecastList>('/api/forecast-runs', signal, query); }
  getForecastDetails(id: string, signal?: AbortSignal) { return this.get<ForecastRunDetails>(`/api/forecast-runs/${encodeURIComponent(id)}`, signal); }
  getJob(id: string, signal?: AbortSignal) { return this.get<JobRecord>(`/api/jobs/${encodeURIComponent(id)}`, signal); }
  getResult(id: string, signal?: AbortSignal) { return this.get<ForecastResult>(`/api/forecast-runs/${encodeURIComponent(id)}/result`, signal); }
  getEvents(id: string, after = 0, signal?: AbortSignal) { return this.get<AgentEvent[]>(`/api/jobs/${encodeURIComponent(id)}/events`, signal, { after, limit: 1000 }); }
  cancelJob(id: string, signal?: AbortSignal) { return this.post<JobRecord>(`/api/jobs/${encodeURIComponent(id)}/cancel`, undefined, undefined, signal); }
  createReplay(request: ReplayRequest, idempotencyKey: string, signal?: AbortSignal) { return this.post<JobRecord>('/api/replays', request, idempotencyKey, signal); }
  getReplayDetails(id: string, signal?: AbortSignal) { return this.get<ReplayDetails>(`/api/replays/${encodeURIComponent(id)}`, signal); }
  listReplayRuns(id: string, signal?: AbortSignal) { return this.get<JobRecord[]>(`/api/replays/${encodeURIComponent(id)}/runs`, signal); }
  getWeather(id: string, signal?: AbortSignal) { return this.get<WeatherDetails>(`/api/forecast-runs/${encodeURIComponent(id)}/weather`, signal); }
  getExplanation(id: string, signal?: AbortSignal) { return this.get<ExplanationDetails>(`/api/forecast-runs/${encodeURIComponent(id)}/explanation`, signal); }
  listEvaluations(query: Query = {}, signal?: AbortSignal) { return this.get<EvaluationList>('/api/evaluations', signal, query); }
  getEvaluation(id: string, signal?: AbortSignal) { return this.get<EvaluationReport>(`/api/evaluations/${encodeURIComponent(id)}`, signal); }
  getDataQuality(signal?: AbortSignal) { return this.get<DataQualityReport>('/api/data-quality', signal); }
  async exportForecast(id: string, signal?: AbortSignal) { return (await this.response(`/api/forecast-runs/${encodeURIComponent(id)}/export`, { signal })).blob(); }
  async exportReplay(id: string, allowPartial = false, signal?: AbortSignal) {
    const r = await this.response(`/api/replays/${encodeURIComponent(id)}/export`, { signal }, { allow_partial: allowPartial });
    return { blob: await r.blob(), status: r.headers.get('X-Replay-Export-Status'), total: Number(r.headers.get('X-Replay-Total')), completed: Number(r.headers.get('X-Replay-Completed')), failed: Number(r.headers.get('X-Replay-Failed')), cancelled: Number(r.headers.get('X-Replay-Cancelled')) };
  }
  /** Unmount: call close(). This stops subscriptions/requests, not the forecast job. */
  subscribeJobEvents(id: string, callbacks: EventCallbacks, after = 0, signal?: AbortSignal): Subscription {
    const controller = new AbortController();
    let last = after, source: EventSource | undefined, polling = false;
    const close = () => { source?.close(); controller.abort(); signal?.removeEventListener('abort', close); };
    if (signal?.aborted) { close(); return { close }; }
    signal?.addEventListener('abort', close, { once: true });
    const receive = (event: AgentEvent) => { if (event.job_id === id && event.event_id > last) { last = event.event_id; callbacks.onEvent(event); } };
    const terminal = (j: JobRecord) => ['completed', 'failed', 'cancelled'].includes(j.status);
    const pause = () => new Promise<void>(resolve => {
      const done = () => { clearTimeout(timer); controller.signal.removeEventListener('abort', done); resolve(); };
      const timer = setTimeout(done, this.pollMilliseconds); controller.signal.addEventListener('abort', done, { once: true });
    });
    const fallback = async () => {
      if (polling || controller.signal.aborted) return;
      polling = true; source?.close();
      while (!controller.signal.aborted) {
        try {
          const j = await this.getJob(id, controller.signal);
          // Status-before-tail ensures terminal state cannot skip final events.
          let events: AgentEvent[];
          do { events = await this.getEvents(id, last, controller.signal); events.forEach(receive); } while (events.length === 1000);
          if (terminal(j)) { callbacks.onEnd({ job_id: id, status: j.status }); close(); return; }
        } catch (error) {
          if (controller.signal.aborted) return;
          callbacks.onError?.(error);
          if (error instanceof ApiException && [400, 404, 410, 422, 501].includes(error.status)) { close(); return; }
        }
        await pause();
      }
    };
    if (typeof EventSource === 'undefined') { void fallback(); return { close }; }
    source = new EventSource(this.url(`/api/jobs/${encodeURIComponent(id)}/stream`, { after }));
    source.addEventListener('agent_event', event => { try { receive(JSON.parse((event as MessageEvent).data) as AgentEvent); } catch (error) { callbacks.onError?.(error); void fallback(); } });
    source.addEventListener('stream_end', event => { try { callbacks.onEnd(JSON.parse((event as MessageEvent).data) as StreamEnd); } finally { close(); } });
    source.addEventListener('stream_error', event => { callbacks.onError?.(JSON.parse((event as MessageEvent).data)); void fallback(); });
    source.onerror = () => { void fallback(); };
    return { close };
  }
}
