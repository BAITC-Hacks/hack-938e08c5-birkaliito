"""Internal HTTP bridge from the Go API to the archived XGBoost forecast.

The registry is intentionally in memory. It is suitable for local integration and
does not claim durable production acceptance or actual GFS run identifiers.
"""

import base64
import binascii
import copy
import hashlib
import json
import logging
import math
import os
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import joblib
import pandas as pd

from .data import read_hourly
from .features import as_utc
from .forecast import forecast
from .weather import ENDPOINT, read_weather, validate_weather

ROOT = Path(__file__).resolve().parents[1]
MAX_BODY = 1 << 20
MAX_EVENTS = 2000
MAX_JOBS = 500
MAX_QUEUE = 64


class APIError(Exception):
    def __init__(self, status, code, message):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def utc(value):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        raise APIError(422, "INVALID_REQUEST", "Timestamp requires an explicit UTC offset")
    return stamp.tz_convert("UTC")


def iso(value):
    return pd.Timestamp(value).tz_convert("UTC").isoformat().replace("+00:00", "Z")


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def cloned(value):
    return copy.deepcopy(value)


class BackendBridge:
    def __init__(self, root=ROOT, model_path=None, weather_path=None, hourly_path=None):
        self.root = Path(root)
        self.lock = threading.RLock()
        self.predict_lock = threading.Lock()
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="wind-forecast")
        self.jobs = {}
        self.keys = {}
        self.error = None
        self.bundle = self.weather = self.hourly = None
        self.model_version = self.feature_version = self.training_cutoff = None
        self.weather_retrieved_at = None
        try:
            model_file = self._path(model_path or "artifacts/improved/model.joblib")
            self.bundle = joblib.load(model_file)
            archive = weather_path or self.bundle.get("weather_archive", "data/weather/archive.csv")
            weather_file = self._path(archive)
            self.weather = read_weather(weather_file)
            validate_weather(self.weather, self.bundle["config"])
            missing = set(self.bundle.get("additional_weather_columns", [])) - set(self.weather)
            if missing:
                raise ValueError("Weather archive does not match the trained feature schema")
            history_file = self._path(hourly_path or "data/processed/hourly.csv")
            self.hourly = read_hourly(history_file) if history_file.exists() else None
            self.model_version = "xgboost-" + hashlib.sha256(model_file.read_bytes()).hexdigest()[:16]
            feature_spec = json.dumps(self.bundle["features"], sort_keys=True).encode()
            self.feature_version = "ml-features-" + hashlib.sha256(feature_spec).hexdigest()[:12]
            zone = self.bundle["config"]["timezone"]
            self.training_cutoff = as_utc(self.bundle["training_max_valid_time"], zone) + pd.Timedelta(hours=1)
            self.weather_retrieved_at = iso(pd.Timestamp(weather_file.stat().st_mtime, unit="s", tz="UTC"))
        except Exception as exc:
            logging.warning("ML artifacts unavailable: %s", exc)
            self.error = "Missing or incompatible model, weather archive, or metadata"

    def _path(self, path):
        path = Path(path)
        return path if path.is_absolute() else self.root / path

    @property
    def ready(self):
        return self.error is None

    def close(self):
        self.pool.shutdown(wait=True, cancel_futures=True)

    def _require_ready(self):
        if not self.ready:
            raise APIError(503, "DEPENDENCY_UNAVAILABLE", self.error)

    def meta(self):
        ready = self.ready
        cap = dict(forecast=ready, replay=ready, cancel=ready, sse=ready,
                   weather_details=ready, shap=False, evaluations=False,
                   data_quality=False, simulated=False)
        config = self.bundle["config"] if ready else {}
        return dict(service="wind-forecast-ml", version="0.1.0", contract_version="1.2.0",
                    agent_mode="http", allowed_data_modes=["real"] if ready else [],
                    display_timezone=config.get("timezone", "Asia/Almaty"),
                    source_timezone_status="confirmed" if config.get("timezone_confirmed") else "unconfirmed",
                    target_unit="normalized_power", normalization_status="unconfirmed",
                    agent_dependency="available" if ready else "unavailable", capabilities=cap)

    def models(self):
        if not self.ready:
            return {"items": [], "next_cursor": None}
        return {"items": [dict(model_version=self.model_version,
                                display_name="XGBoost · архив GFS · эмпирический интервал 10–90%",
                                data_mode="real", feature_version=self.feature_version,
                                training_data_available_through=iso(self.training_cutoff),
                                supports_quantiles=True, availability="ready")],
                "next_cursor": None}

    def _request(self, raw):
        self._require_ready()
        if not isinstance(raw, dict) or set(raw) - {"forecast_origin", "horizon_hours", "turbine_ids", "model_version", "mode", "data_mode"}:
            raise APIError(422, "INVALID_REQUEST", "Invalid forecast request")
        try:
            origin = utc(raw["forecast_origin"])
            model = raw["model_version"]
        except (KeyError, TypeError, ValueError) as exc:
            raise APIError(422, "INVALID_REQUEST", "Invalid forecast origin or model") from exc
        horizon = raw.get("horizon_hours", 48)
        ids = raw.get("turbine_ids", [1, 2])
        mode = raw.get("mode", "replay")
        if origin != origin.floor("h") or type(horizon) is not int or horizon not in (24, 48) or not isinstance(ids, list) or len(ids) not in (1, 2) or any(type(i) is not int or i not in (1, 2) for i in ids) or len(set(ids)) != len(ids) or mode not in ("replay", "live") or raw.get("data_mode", "real") != "real" or model != self.model_version:
            raise APIError(422, "INVALID_REQUEST", "Forecast parameters or model are unavailable")
        if origin < self.training_cutoff:
            raise APIError(422, "MODEL_UNAVAILABLE", "Model training data were unavailable at this origin")
        return dict(forecast_origin=iso(origin), horizon_hours=horizon,
                    turbine_ids=sorted(ids), model_version=model, mode=mode, data_mode="real")

    def _replay_request(self, raw):
        if not isinstance(raw, dict) or set(raw) - {"origins", "horizon_hours", "turbine_ids", "model_version", "data_mode"}:
            raise APIError(422, "INVALID_REQUEST", "Invalid replay request")
        origins = raw.get("origins")
        if not isinstance(origins, list) or not 1 <= len(origins) <= 366:
            raise APIError(422, "INVALID_REQUEST", "Replay needs 1..366 origins")
        normalized = [self._request({"forecast_origin": item, "horizon_hours": raw.get("horizon_hours", 48),
                                     "turbine_ids": raw.get("turbine_ids", [1, 2]),
                                     "model_version": raw.get("model_version"), "data_mode": raw.get("data_mode", "real")}) for item in origins]
        canonical = [item["forecast_origin"] for item in normalized]
        if len(set(canonical)) != len(canonical):
            raise APIError(422, "INVALID_REQUEST", "Duplicate replay origins")
        first = normalized[0]
        return dict(origins=canonical, horizon_hours=first["horizon_hours"],
                    turbine_ids=first["turbine_ids"], model_version=first["model_version"], data_mode="real")

    def _event(self, job, kind, node, message):
        record = job["record"]
        record["updated_at"] = now()
        record["stage"] = node
        event_id = job["next_event"]
        job["next_event"] += 1
        job["events"].append(dict(event_id=event_id, job_id=record["job_id"], recorded_at=record["updated_at"],
                                  kind=kind, node=node, message=message, evidence_refs=[]))
        if len(job["events"]) > MAX_EVENTS:
            job["events"] = job["events"][-MAX_EVENTS:]

    def _new_job(self, kind, request, parent=None):
        job_id = "real-" + uuid.uuid4().hex
        stamp = now()
        job = dict(record=dict(job_id=job_id, job_type=kind, status="queued", created_at=stamp,
                               updated_at=stamp, stage="queued", error_code=None, error_message=None),
                   request=cloned(request), parent=parent, children=[], cancel_requested=False,
                   result=None, weather=None, events=[], next_event=1, future=None)
        self.jobs[job_id] = job
        self._event(job, "tool_requested", "queued", "Задание принято в локальную очередь ML")
        return job

    def _accept_key(self, endpoint, key, fingerprint):
        if not isinstance(key, str) or not 1 <= len(key) <= 128 or any(ord(c) < 33 or ord(c) > 126 for c in key):
            raise APIError(422, "INVALID_REQUEST", "Valid Idempotency-Key is required")
        prior = self.keys.get((endpoint, key))
        if prior is not None:
            if prior[0] != fingerprint:
                raise APIError(409, "IDEMPOTENCY_CONFLICT", "Idempotency key has a different request")
            return self.jobs[prior[1]]
        return None

    def _capacity(self, count):
        queued = sum(job["record"]["status"] == "queued" for job in self.jobs.values())
        if len(self.jobs) + count > MAX_JOBS or queued + count > MAX_QUEUE:
            raise APIError(503, "QUEUE_FULL", "Local ML job capacity is full")

    def create_forecast(self, raw, key):
        request = self._request(raw)
        fingerprint = json.dumps(request, sort_keys=True)
        with self.lock:
            old = self._accept_key("forecast", key, fingerprint)
            if old is not None:
                return cloned(old["record"])
            self._capacity(1)
            job = self._new_job("forecast", request)
            self.keys[("forecast", key)] = (fingerprint, job["record"]["job_id"])
            job["future"] = self.pool.submit(self._run_forecast, job["record"]["job_id"])
            return cloned(job["record"])

    def create_replay(self, raw, key):
        request = self._replay_request(raw)
        fingerprint = json.dumps({**request, "origins": sorted(request["origins"])}, sort_keys=True)
        with self.lock:
            old = self._accept_key("replay", key, fingerprint)
            if old is not None:
                return cloned(old["record"])
            self._capacity(len(request["origins"]) + 1)
            parent = self._new_job("replay", request)
            self.keys[("replay", key)] = (fingerprint, parent["record"]["job_id"])
            parent["record"]["status"] = "running"
            self._event(parent, "started", "replay", "Пакетный прогноз запущен")
            for origin in request["origins"]:
                child_request = dict(forecast_origin=origin, horizon_hours=request["horizon_hours"],
                                     turbine_ids=cloned(request["turbine_ids"]), model_version=request["model_version"],
                                     mode="replay", data_mode="real")
                child = self._new_job("forecast", child_request, parent["record"]["job_id"])
                parent["children"].append(child["record"]["job_id"])
            for child_id in parent["children"]:
                self.jobs[child_id]["future"] = self.pool.submit(self._run_forecast, child_id)
            return cloned(parent["record"])

    def _provenance(self, weather):
        runs = []
        for offset, group in weather.groupby("forecast_offset_days", sort=True):
            ordered = group.sort_values(["valid_time", "turbine_id"])
            digest = hashlib.sha256(ordered.to_json(orient="records", date_format="iso", double_precision=10).encode()).hexdigest()
            runs.append(dict(provider="GFS", run_id=f"previous-runs-day{int(offset)}-{digest[:12]}",
                             initialization_time=iso(group.source_reference_time_upper_bound.max()),
                             effective_available_at=iso(group.available_at_upper_bound.max()),
                             availability_basis="conservative_policy",
                             availability_policy_id="openmeteo-previous-runs-6h-v1",
                             retrieved_at=self.weather_retrieved_at,
                             source_reference=f"{ENDPOINT}#gfs_global_previous_day{int(offset)}",
                             content_sha256=digest))
        return runs

    def _artifacts(self, frame, request, job_id):
        frame = frame[frame.turbine_id.isin(request["turbine_ids"])].sort_values(["turbine_id", "horizon_hours"])
        expected = request["horizon_hours"] * len(request["turbine_ids"])
        if len(frame) != expected or frame[["prediction", "lower_80", "upper_80"]].isna().any().any():
            raise ValueError("ML result has missing forecast rows or intervals")
        keys = frame[["valid_time", "turbine_id", "forecast_offset_days"]]
        weather = keys.merge(self.weather, on=["valid_time", "turbine_id", "forecast_offset_days"],
                             how="left", validate="one_to_one")
        if len(weather) != expected or weather.wind_speed_100m.isna().any():
            raise ValueError("Weather artifact is incomplete")
        runs = self._provenance(weather)
        points = []
        weather_points = []
        for row in frame.itertuples():
            mean, lo, hi = float(row.prediction), float(row.lower_80), float(row.upper_80)
            if not all(math.isfinite(value) for value in (mean, lo, hi)) or lo > hi:
                raise ValueError("ML result has invalid interval values")
            points.append(dict(turbine_id=int(row.turbine_id), valid_time=iso(row.valid_time),
                               interval_end=iso(row.valid_time + pd.Timedelta(hours=1)),
                               lead_hours=int(row.horizon_hours), power_mean=mean,
                               q10=lo, q50=None, q90=hi))
        for row in weather.itertuples():
            weather_points.append(dict(turbine_id=int(row.turbine_id), valid_time=iso(row.valid_time),
                                       wind_speed_ms=float(row.wind_speed_100m), wind_height_m=100.0,
                                       temperature_c=float(row.temperature_2m), is_interpolated=False))
        fallback = self.bundle.get("history_model") is not None and frame.prediction_mode.eq("weather_only").any()
        warnings = ["q50 не рассчитан этой моделью; null не заменяется средним прогнозом.",
                    "Open-Meteo Previous Runs не сообщает фактический ID выпуска GFS; run_id обозначает группу архивных значений, доступность оценена консервативно."]
        if fallback:
            warnings.append("Часть прогноза рассчитана только по погоде: свежая история SCADA недоступна.")
        result = dict(run_id=job_id, forecast_origin=request["forecast_origin"],
                      horizon_hours=request["horizon_hours"], turbine_ids=cloned(request["turbine_ids"]),
                      data_mode="real", model_version=self.model_version, feature_version=self.feature_version,
                      training_data_available_through=iso(self.training_cutoff),
                      quality_status="degraded" if fallback else "passed",
                      explanation_status="template", explanation="Прогноз XGBoost по архивной погоде; SHAP не рассчитан.",
                      warnings=warnings, weather_runs=runs, points=points)
        weather_result = dict(run_id=job_id, data_mode="real", status="available",
                              weather_runs=cloned(runs), points=weather_points)
        return result, weather_result

    def _cancel_locked(self, job):
        job["record"]["status"] = "cancelled"
        self._event(job, "warning", "cancelled", "Задание отменено")
        if job["parent"]:
            self._refresh_parent_locked(job["parent"])

    def _refresh_parent_locked(self, parent_id):
        parent = self.jobs[parent_id]
        counts = self._counts(parent)
        if counts["queued"] or counts["running"]:
            return
        if parent["record"]["status"] in ("completed", "failed", "cancelled"):
            return
        if parent["cancel_requested"] or counts["cancelled"]:
            parent["record"]["status"] = "cancelled"
            self._event(parent, "warning", "cancelled", "Пакетный прогноз отменён")
        elif counts["failed"]:
            parent["record"]["status"] = "failed"
            parent["record"]["error_code"] = "REPLAY_CHILD_FAILED"
            parent["record"]["error_message"] = "One or more child forecasts failed"
            self._event(parent, "failed", "failed", "Часть прогнозов завершилась ошибкой")
        else:
            parent["record"]["status"] = "completed"
            self._event(parent, "completed", "completed", "Пакетный прогноз завершён")

    def _run_forecast(self, job_id):
        with self.lock:
            job = self.jobs[job_id]
            if job["cancel_requested"]:
                self._cancel_locked(job)
                return
            job["record"]["status"] = "running"
            self._event(job, "started", "forecast", "Модель рассчитывает прогноз")
            request = cloned(job["request"])
        try:
            with self.predict_lock:
                frame = forecast(self.bundle, self.weather, request["forecast_origin"],
                                 request["horizon_hours"], hourly=self.hourly)
            result, weather = self._artifacts(frame, request, job_id)
        except Exception:
            logging.exception("ML forecast failed for %s", job_id)
            with self.lock:
                if job["cancel_requested"]:
                    self._cancel_locked(job)
                else:
                    job["record"]["status"] = "failed"
                    job["record"]["error_code"] = "ML_FORECAST_FAILED"
                    job["record"]["error_message"] = "ML forecast could not be completed; inspect the Python service log"
                    self._event(job, "failed", "failed", "Расчёт прогноза не выполнен")
                    if job["parent"]:
                        self._refresh_parent_locked(job["parent"])
            return
        with self.lock:
            if job["cancel_requested"]:
                self._cancel_locked(job)
            else:
                job["result"], job["weather"] = result, weather
                job["record"]["status"] = "completed"
                self._event(job, "completed", "completed", "Прогноз рассчитан")
                if job["parent"]:
                    self._refresh_parent_locked(job["parent"])

    def _job(self, job_id, kind=None):
        job = self.jobs.get(job_id)
        if job is None or kind is not None and job["record"]["job_type"] != kind:
            raise APIError(404, "NOT_FOUND", "Job not found")
        return job

    def get_job(self, job_id):
        with self.lock:
            return cloned(self._job(job_id)["record"])

    def forecast_details(self, job_id):
        with self.lock:
            job = self._job(job_id, "forecast")
            return dict(job=cloned(job["record"]), request=cloned(job["request"]),
                        parent_replay_id=job["parent"], result_available=job["result"] is not None,
                        cancel_requested=job["cancel_requested"])

    def result(self, job_id):
        with self.lock:
            job = self._job(job_id, "forecast")
            if job["result"] is None:
                raise APIError(409, "RESULT_NOT_READY", "Forecast result is not available")
            return cloned(job["result"])

    def weather_details(self, job_id):
        with self.lock:
            job = self._job(job_id, "forecast")
            if job["weather"] is None:
                raise APIError(409, "RESULT_NOT_READY", "Weather artifact is not available")
            return cloned(job["weather"])

    def explanation(self, job_id):
        result = self.result(job_id)
        return dict(run_id=job_id, data_mode="real", status="template",
                    text=result["explanation"], shap_status="unavailable", shap_items=[])

    def events(self, job_id, after, limit):
        if after < 0 or after > 9007199254740991 or not 1 <= limit <= 1000:
            raise APIError(400, "INVALID_CURSOR", "Invalid event cursor or limit")
        with self.lock:
            events = self._job(job_id)["events"]
            if events and after < events[0]["event_id"] - 1:
                raise APIError(410, "EVENT_CURSOR_EXPIRED", "Event cursor has expired")
            return cloned([event for event in events if event["event_id"] > after][:limit])

    def cancel(self, job_id):
        with self.lock:
            job = self._job(job_id)
            if job["record"]["status"] in ("completed", "failed"):
                raise APIError(409, "JOB_NOT_CANCELLABLE", "Terminal job cannot be cancelled")
            if job["record"]["status"] == "cancelled":
                return cloned(job["record"]), 200
            job["cancel_requested"] = True
            if job["record"]["job_type"] == "replay":
                for child_id in job["children"]:
                    child = self.jobs[child_id]
                    if child["record"]["status"] in ("queued", "running"):
                        child["cancel_requested"] = True
                        if child["future"] and child["future"].cancel():
                            self._cancel_locked(child)
                self._refresh_parent_locked(job_id)
            elif job["future"] and job["future"].cancel():
                self._cancel_locked(job)
            return cloned(job["record"]), 200 if job["record"]["status"] == "cancelled" else 202

    def _counts(self, parent):
        counts = dict(total=len(parent["children"]), queued=0, running=0,
                      completed=0, failed=0, cancelled=0)
        for child_id in parent["children"]:
            counts[self.jobs[child_id]["record"]["status"]] += 1
        return counts

    def replay_details(self, job_id):
        with self.lock:
            parent = self._job(job_id, "replay")
            counts = self._counts(parent)
            return dict(job=cloned(parent["record"]), request=cloned(parent["request"]),
                        cancel_requested=parent["cancel_requested"], counters=counts,
                        has_failures=counts["failed"] > 0)

    def replay_runs(self, job_id):
        with self.lock:
            parent = self._job(job_id, "replay")
            return [cloned(self.jobs[child_id]["record"]) for child_id in parent["children"]]

    def list_forecasts(self, params):
        try:
            limit = int(params.get("limit", [25])[0])
            turbine = int(params.get("turbine_id", [0])[0])
        except ValueError as exc:
            raise APIError(400, "INVALID_CURSOR", "Invalid list filter") from exc
        if not 1 <= limit <= 100 or turbine not in (0, 1, 2):
            raise APIError(422, "INVALID_REQUEST", "Invalid list limit or turbine")
        status = params.get("status", [""])[0]
        data_mode = params.get("data_mode", [""])[0]
        if status and status not in ("queued", "running", "completed", "failed", "cancelled") or data_mode and data_mode != "real":
            raise APIError(422, "INVALID_REQUEST", "Invalid list status or data mode")
        try:
            start = utc(params["forecast_origin_from"][0]) if "forecast_origin_from" in params else None
            end = utc(params["forecast_origin_to"][0]) if "forecast_origin_to" in params else None
        except (ValueError, TypeError) as exc:
            raise APIError(422, "INVALID_REQUEST", "Invalid origin filter") from exc
        if start is not None and end is not None and start >= end:
            raise APIError(422, "INVALID_REQUEST", "Origin range must increase")
        filter_key = hashlib.sha256(json.dumps([limit, turbine, status, data_mode,
                                                iso(start) if start is not None else None,
                                                iso(end) if end is not None else None]).encode()).hexdigest()[:16]
        after = None
        cursor = params.get("cursor", [""])[0]
        if cursor:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
                if decoded["filter"] != filter_key or not isinstance(decoded["after"], list) or len(decoded["after"]) != 2:
                    raise ValueError("cursor mismatch")
                after = tuple(decoded["after"])
            except (ValueError, KeyError, TypeError, binascii.Error) as exc:
                raise APIError(400, "INVALID_CURSOR", "Invalid list cursor") from exc
        with self.lock:
            jobs = [job for job in self.jobs.values() if job["record"]["job_type"] == "forecast"]
            jobs.sort(key=lambda job: (job["record"]["created_at"], job["record"]["job_id"]), reverse=True)
            selected = []
            for job in jobs:
                req = job["request"]
                origin = pd.Timestamp(req["forecast_origin"])
                if after and (job["record"]["created_at"], job["record"]["job_id"]) >= after:
                    continue
                if turbine and turbine not in req["turbine_ids"] or status and status != job["record"]["status"] or start is not None and origin < start or end is not None and origin >= end:
                    continue
                selected.append(job)
            page = selected[:limit]
            next_cursor = None
            if len(selected) > limit:
                payload = json.dumps({"filter": filter_key, "after": [page[-1]["record"]["created_at"], page[-1]["record"]["job_id"]]}).encode()
                next_cursor = base64.urlsafe_b64encode(payload).decode().rstrip("=")
            items = [dict(job=cloned(job["record"]), request=cloned(job["request"]),
                          parent_replay_id=job["parent"], result_available=job["result"] is not None,
                          cancel_requested=job["cancel_requested"]) for job in page]
            return dict(items=items, next_cursor=next_cursor)


def make_handler(bridge, token=""):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, value):
            body = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def dispatch(self, method):
            try:
                if token and self.headers.get("Authorization") != "Bearer " + token:
                    raise APIError(401, "UNAUTHORIZED", "Internal token required")
                parsed = urlsplit(self.path)
                if not parsed.path.startswith("/internal/v1/"):
                    raise APIError(404, "NOT_FOUND", "Route not found")
                parts = parsed.path[len("/internal/v1/"):].split("/")
                params = parse_qs(parsed.query, keep_blank_values=True)
                if method == "GET":
                    value = self.get(parts, params)
                    self.respond(200, value)
                else:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length < 0 or length > MAX_BODY:
                        raise APIError(413, "BODY_TOO_LARGE", "Request body exceeds limit")
                    if self.headers.get_content_type() != "application/json":
                        raise APIError(415, "UNSUPPORTED_MEDIA_TYPE", "Expected application/json")
                    raw = json.loads(self.rfile.read(length)) if length else None
                    value, status = self.post(parts, raw)
                    self.respond(status, value)
            except APIError as exc:
                self.respond(exc.status, dict(code=exc.code, message=exc.message, request_id=self.headers.get("X-Request-ID")))
            except (ValueError, TypeError, json.JSONDecodeError):
                self.respond(400, dict(code="INVALID_REQUEST", message="Malformed request", request_id=self.headers.get("X-Request-ID")))
            except Exception:
                logging.exception("Internal ML API request failed")
                self.respond(500, dict(code="INTERNAL_ERROR", message="Internal ML service error", request_id=self.headers.get("X-Request-ID")))

        def get(self, parts, params):
            if parts == ["readyz"]:
                bridge._require_ready()
                return {"status": "ok"}
            if parts == ["meta"]:
                return bridge.meta()
            if parts == ["models"]:
                return bridge.models()
            if parts == ["forecast-runs"]:
                return bridge.list_forecasts(params)
            if len(parts) == 2 and parts[0] == "forecast-runs":
                return bridge.forecast_details(parts[1])
            if len(parts) == 3 and parts[0] == "forecast-runs":
                if parts[2] == "result":
                    return bridge.result(parts[1])
                if parts[2] == "weather":
                    return bridge.weather_details(parts[1])
                if parts[2] == "explanation":
                    return bridge.explanation(parts[1])
            if len(parts) == 2 and parts[0] == "jobs":
                return bridge.get_job(parts[1])
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "events":
                return bridge.events(parts[1], int(params.get("after", [0])[0]),
                                     int(params.get("limit", [100])[0]))
            if len(parts) == 2 and parts[0] == "replays":
                return bridge.replay_details(parts[1])
            if len(parts) == 3 and parts[0] == "replays" and parts[2] == "runs":
                return bridge.replay_runs(parts[1])
            if parts[0] in ("evaluations", "data-quality"):
                raise APIError(501, "FEATURE_NOT_SUPPORTED", "ML read model is not implemented")
            raise APIError(404, "NOT_FOUND", "Route not found")

        def post(self, parts, raw):
            if parts == ["forecast-runs"]:
                return bridge.create_forecast(raw, self.headers.get("Idempotency-Key")), 202
            if parts == ["replays"]:
                return bridge.create_replay(raw, self.headers.get("Idempotency-Key")), 202
            if len(parts) == 3 and parts[0] == "jobs" and parts[2] == "cancel":
                return bridge.cancel(parts[1])
            raise APIError(404, "NOT_FOUND", "Route not found")

        def do_GET(self):
            self.dispatch("GET")

        def do_POST(self):
            self.dispatch("POST")

    return Handler


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    bridge = BackendBridge(model_path=os.getenv("ML_MODEL_PATH"),
                           weather_path=os.getenv("ML_WEATHER_PATH"),
                           hourly_path=os.getenv("ML_HOURLY_PATH"))
    address = os.getenv("ML_HTTP_ADDR", "127.0.0.1:8000")
    host, port = address.rsplit(":", 1)
    server = ThreadingHTTPServer((host, int(port)), make_handler(bridge, os.getenv("ML_INTERNAL_TOKEN", "")))
    logging.info("ML internal API on %s; ready=%s", address, bridge.ready)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        bridge.close()


if __name__ == "__main__":
    main()
