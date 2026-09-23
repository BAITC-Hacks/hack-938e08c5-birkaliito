// Generated from the canonical contract. Timestamps are RFC3339; output UTC.
export interface ForecastRequest {
  forecast_origin: string;
  horizon_hours?: 24 | 48;
  turbine_ids?: Array<1 | 2>;
  model_version: string;
  mode?: "replay" | "live";
  data_mode?: "real" | "fixture";
}
export interface ReplayRequest {
  origins: Array<string>;
  horizon_hours?: 24 | 48;
  turbine_ids?: Array<1 | 2>;
  model_version: string;
  data_mode?: "real" | "fixture";
}
export interface JobRecord {
  job_id: string;
  job_type: "forecast" | "replay";
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  created_at: string;
  updated_at: string;
  stage: string;
  error_code: string | null;
  error_message: string | null;
}
export interface ForecastPoint {
  turbine_id: 1 | 2;
  valid_time: string;
  interval_end: string;
  lead_hours: number;
  power_mean: number;
  q10: number;
  q50: number;
  q90: number;
}
export interface WeatherProvenance {
  provider: "GFS";
  run_id: string;
  initialization_time: string;
  effective_available_at: string;
  availability_basis: "observed_publication" | "conservative_policy";
  availability_policy_id: string | null;
  retrieved_at: string;
  source_reference: string;
  content_sha256: string;
}
export interface ForecastResult {
  run_id: string;
  forecast_origin: string;
  horizon_hours: 24 | 48;
  turbine_ids: Array<1 | 2>;
  data_mode: "real" | "fixture";
  model_version: string;
  feature_version: string;
  training_data_available_through: string;
  quality_status: "passed" | "degraded";
  explanation_status: "llm" | "template" | "unavailable";
  explanation: string;
  warnings: Array<string>;
  weather_runs: Array<WeatherProvenance>;
  points: Array<ForecastPoint>;
}
export interface AgentEvent {
  event_id: number;
  job_id: string;
  recorded_at: string;
  kind: "started" | "tool_requested" | "tool_completed" | "policy_rejected" | "warning" | "completed" | "failed";
  node: string;
  message: string;
  evidence_refs: Array<string>;
}
export interface ApiError {
  code: string;
  message: string;
  request_id: string | null;
}
export interface Capabilities {
  forecast: boolean;
  replay: boolean;
  cancel: boolean;
  sse: boolean;
  weather_details: boolean;
  shap: boolean;
  evaluations: boolean;
  data_quality: boolean;
  simulated: boolean;
}
export interface Meta {
  service: string;
  version: string;
  contract_version: string;
  agent_mode: "mock" | "http";
  allowed_data_modes: Array<"real" | "fixture">;
  display_timezone: string;
  source_timezone_status: "unconfirmed" | "confirmed";
  target_unit: "normalized_power";
  normalization_status: "unconfirmed" | "confirmed";
  agent_dependency: "available" | "unavailable";
  capabilities: Capabilities;
}
export interface Turbine {
  id: 1 | 2;
  name: string;
  latitude: number;
  longitude: number;
  rated_power_mw: number | null;
  hub_height_m: number | null;
  metadata_status: "configured_unverified" | "verified";
}
export interface Model {
  model_version: string;
  display_name: string;
  data_mode: "real" | "fixture";
  feature_version: string;
  training_data_available_through: string;
  supports_quantiles: boolean;
  availability: "ready" | "unavailable";
}
export interface ForecastRunDetails {
  job: JobRecord;
  request: ForecastRequest;
  parent_replay_id: string | null;
  result_available: boolean;
  cancel_requested: boolean;
}
export interface ReplayCounters {
  total: number;
  queued: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
}
export interface ReplayDetails {
  job: JobRecord;
  request: ReplayRequest;
  cancel_requested: boolean;
  counters: ReplayCounters;
  has_failures: boolean;
}
export interface WeatherPoint {
  turbine_id: 1 | 2;
  valid_time: string;
  wind_speed_ms: number | null;
  wind_height_m: number | null;
  temperature_c: number | null;
  is_interpolated: boolean;
}
export interface WeatherDetails {
  run_id: string;
  data_mode: "real" | "fixture";
  status: "available" | "unavailable";
  weather_runs: Array<WeatherProvenance>;
  points: Array<WeatherPoint>;
}
export interface FeatureContribution {
  feature: string;
  value: number;
  contribution: number;
}
export interface SHAPItem {
  turbine_id: 1 | 2;
  valid_time: string;
  output: "power_mean";
  base_value: number;
  prediction: number;
  feature_contributions: Array<FeatureContribution>;
  output_unit: "normalized_power";
}
export interface ExplanationDetails {
  run_id: string;
  data_mode: "real" | "fixture";
  status: "llm" | "template" | "unavailable";
  text: string;
  shap_status: "available" | "unavailable";
  shap_items: Array<SHAPItem>;
}
export interface EvaluationMetric {
  turbine_id: 1 | 2;
  lead_from: number;
  lead_to: number;
  mae: number | null;
  rmse: number | null;
  bias: number | null;
  coverage_q10_q90: number | null;
  mean_interval_width: number | null;
}
export interface EvaluationReport {
  evaluation_id: string;
  data_mode: "real" | "fixture";
  status: "available" | "unavailable";
  model_version: string;
  baseline_name: string;
  target_unit: "normalized_power";
  evaluation_scope: "end_to_end" | "power_conversion_only";
  period_start: string;
  period_end: string;
  training_data_available_through: string;
  n_observations: number | null;
  metrics: Array<EvaluationMetric>;
  notes: Array<string>;
}
export interface TurbineQuality {
  turbine_id: 1 | 2;
  range_start: string | null;
  range_end: string | null;
  row_count: number | null;
  complete_hour_count: number | null;
  missing_hour_count: number | null;
  warnings: Array<string>;
}
export interface DataQualityReport {
  status: "available" | "unavailable";
  generated_at: string | null;
  data_mode: "real" | "fixture";
  source_reference: string | null;
  turbines: Array<TurbineQuality>;
}
export interface TurbineList {
  items: Array<Turbine>;
  next_cursor: string | null;
}
export interface ModelList {
  items: Array<Model>;
  next_cursor: string | null;
}
export interface ForecastList {
  items: Array<ForecastRunDetails>;
  next_cursor: string | null;
}
export interface EvaluationList {
  items: Array<EvaluationReport>;
  next_cursor: string | null;
}
export interface Health {
  status: "ok";
}
export interface StreamEnd {
  job_id: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
}
