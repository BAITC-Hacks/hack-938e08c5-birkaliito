"""Small local UI backed by the existing, frozen forecasting models.

Run from the repository root: python -m wind_forecast.ui
No downloads, fitting, or writes to the trained artifacts are performed.
"""

import argparse
import json
import logging
import math
import threading
import uuid
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import joblib
import pandas as pd

from .data import read_hourly
from .forecast import forecast
from .model import predict_details, scores
from .weather import read_weather
from .features import as_utc
from .uploads import FIELD_LIMITS, MAX_CSV_BYTES, parse_upload, weather_template

ROOT = Path(__file__).resolve().parents[1]
MODES = {
    "check": {"label": "Проверка на январе", "min": "2026-01-01", "max": "2026-01-31", "default": "2026-01-10"},
    "forecast": {"label": "Прогноз на февраль", "min": "2026-02-01", "max": "2026-02-28", "default": "2026-02-01"},
    "scenario": {"label": "Своя погода", "min": "2026-02-01", "max": "2026-02-28", "default": "2026-02-01"},
    "csv": {"label": "Загрузить CSV", "min": "2026-01-01", "max": "2099-12-31", "default": "2026-02-01"},
}
SCENARIO_FIELDS = FIELD_LIMITS


def validate_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("Ожидается объект с параметрами прогноза.")
    mode = payload.get("mode", "check")
    if not isinstance(mode, str) or mode not in MODES:
        raise ValueError("Выберите доступный режим.")
    turbine = payload.get("turbine", 1)
    horizon = payload.get("horizon", 48)
    if type(turbine) is not int or turbine not in (1, 2):
        raise ValueError("Выберите турбину 1 или 2.")
    if type(horizon) is not int or horizon not in (24, 48):
        raise ValueError("Горизонт должен быть 24 или 48 часов.")
    date = payload.get("date", MODES[mode]["default"])
    if not isinstance(date, str) or len(date) != 10:
        raise ValueError("Дата должна иметь формат ГГГГ-ММ-ДД.")
    try:
        day = pd.Timestamp(date)
    except ValueError as exc:
        raise ValueError("Укажите корректную дату.") from exc
    if day.strftime("%Y-%m-%d") != date or not MODES[mode]["min"] <= date <= MODES[mode]["max"]:
        raise ValueError(f"Для этого режима выберите дату {MODES[mode]['min']}…{MODES[mode]['max']}.")
    history = payload.get("history", True)
    if not isinstance(history, bool):
        raise ValueError("Параметр истории должен быть логическим значением.")
    values = {}
    if mode == "scenario":
        supplied = payload.get("weather", {})
        if not isinstance(supplied, dict):
            raise ValueError("Укажите значения погоды.")
        for field, (minimum, maximum) in SCENARIO_FIELDS.items():
            try:
                value = float(supplied[field])
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"Нужно числовое значение {field}.") from exc
            if not math.isfinite(value) or not minimum <= value <= maximum:
                raise ValueError(f"{field}: допустимый диапазон {minimum}…{maximum}.")
            values[field] = value
    return {"mode": mode, "date": date, "turbine": turbine, "horizon": horizon,
            "history": history, "weather": values, "upload_id": payload.get("upload_id")}


class ForecastApp:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.evaluation = joblib.load(self.root / "artifacts/improved/evaluation_model.joblib")
        self.production = joblib.load(self.root / "artifacts/improved/model.joblib")
        self.hourly = read_hourly(self.root / "data/processed/hourly.csv")
        self.weather = read_weather(self.root / "data/weather/archive.csv")
        self.lock = threading.Lock()
        self.uploads = OrderedDict()

    def status(self):
        return {"ready": True, "timezone": self.production["config"]["timezone"], "modes": MODES,
                "max_csv_bytes": MAX_CSV_BYTES}

    def upload(self, payload):
        if not isinstance(payload, dict):
            raise ValueError("Ожидается CSV-файл.")
        zone = self.production["config"]["timezone"]
        parsed = parse_upload(payload.get("csv_text"), zone)
        valid = parsed["frame"]
        if parsed["kind"] == "scada":
            valid = valid[valid.power.notna()]
        if valid.empty:
            raise ValueError("В CSV нет полных часов. Для CSV турбины нужны шесть корректных 10-минутных измерений на каждый час.")
        dates = valid.valid_time.dt.tz_convert(zone)
        earliest = max(dates.min().strftime("%Y-%m-%d"), "2026-01-01")
        latest = dates.max().strftime("%Y-%m-%d")
        if parsed["kind"] == "scada":
            latest = min(latest, "2026-02-28")
        if earliest > latest:
            raise ValueError("Нет подходящих дат для готовой модели. Нужны данные с января 2026; для CSV турбины архив погоды доступен до февраля 2026.")
        metadata = {"kind": parsed["kind"], "label": "Почасовая погода" if parsed["kind"] == "weather" else "Измерения турбины",
                    "source_rows": parsed["source_rows"], "hours": int(valid.valid_time.nunique()),
                    "min": earliest, "max": latest, "default": earliest,
                    "timezone": zone, "turbines": sorted(valid.turbine_id.unique().tolist()) if parsed["kind"] == "weather" and "turbine_id" in valid else [1, 2]}
        upload_id = uuid.uuid4().hex
        with self.lock:
            self.uploads[upload_id] = parsed
            while len(self.uploads) > 3:
                self.uploads.popitem(last=False)
        return {**metadata, "upload_id": upload_id}

    def csv_frame(self, request):
        upload_id = request["upload_id"]
        if not isinstance(upload_id, str) or upload_id not in self.uploads:
            raise ValueError("Выберите CSV заново: файл ещё не загружен или сервер был перезапущен.")
        uploaded = self.uploads[upload_id]
        zone = self.production["config"]["timezone"]
        bundle = self.evaluation if request["date"] < "2026-02-01" else self.production
        first = pd.Timestamp(request["date"]).tz_localize(zone)
        issue = first - pd.Timedelta(hours=1)
        warnings = []
        if uploaded["kind"] == "scada":
            hourly = uploaded["frame"].assign(turbine_id=request["turbine"])
            targets = pd.date_range(first.tz_convert("UTC"), periods=request["horizon"], freq="h")
            weather = self.weather[self.weather.valid_time.isin(targets)]
            frame = forecast(bundle, weather, issue, request["horizon"], hourly=hourly if request["history"] else None)
            frame = frame[frame.turbine_id == request["turbine"]].copy()
            frame = frame.merge(weather[["valid_time", "turbine_id", "forecast_offset_days", *SCENARIO_FIELDS]],
                                on=["valid_time", "turbine_id", "forecast_offset_days"], validate="one_to_one")
            frame = frame.merge(hourly[["valid_time", "turbine_id", "power"]].rename(columns={"power": "actual"}),
                                on=["valid_time", "turbine_id"], how="left", validate="many_to_one")
            quality = uploaded["profile"]
            warnings.append(f"Факт и история взяты из вашего CSV, погода — из локального архива GFS. Полных часов в файле: {quality['valid_hours']}; пропущенных или неполных: {quality['missing_or_incomplete_hours']}; некорректных строк: {quality['invalid_rows']}.")
            if request["history"] and frame.prediction_mode.eq("weather_only").any():
                warnings.append("Свежей истории недостаточно: для части часов используется только погода.")
        else:
            frame = uploaded["frame"].copy()
            if "turbine_id" in frame:
                frame = frame[frame.turbine_id == request["turbine"]]
            else:
                frame["turbine_id"] = request["turbine"]
            local_dates = frame.valid_time.dt.tz_convert(zone).dt.strftime("%Y-%m-%d")
            starts = frame.loc[local_dates.eq(request["date"]), "valid_time"]
            if starts.empty:
                raise ValueError("В CSV нет погоды для выбранной даты и турбины.")
            first = starts.min().tz_convert(zone)
            issue = first - pd.Timedelta(hours=1)
            frame = frame[frame.valid_time >= first].head(request["horizon"]).reset_index(drop=True)
            expected = pd.date_range(first.tz_convert("UTC"), periods=len(frame), freq="h")
            if not frame.valid_time.eq(expected).all():
                raise ValueError("В выбранном периоде CSV есть пропуски часов. Нужна последовательная почасовая погода.")
            for key in ("training_max_valid_time", "calibration_max_valid_time"):
                if as_utc(bundle[key], zone) + pd.Timedelta(hours=1) > issue:
                    raise ValueError("Дата CSV раньше доступности готовой модели. Выберите более поздний период.")
            if "weather_issued_at" in frame and (frame.weather_issued_at > issue.tz_convert("UTC")).any():
                raise ValueError("В CSV указана погода, выпущенная позже момента прогноза мощности.")
            frame["issued_at"] = issue.tz_convert("UTC")
            frame["horizon_hours"] = range(1, len(frame) + 1)
            frame["forecast_offset_days"] = (frame.horizon_hours > 24).astype(int) + 2
            details = predict_details({**bundle, "use_history": False}, frame.drop(columns="actual"))
            for column in details:
                frame[column] = details[column]
            frame[["lower_80", "upper_80"]] = float("nan")
            warnings.append("Прогноз по погоде из вашего CSV, без истории. Источник и доступность погоды не подтверждены; интервалы, откалиброванные на архиве GFS, здесь не показаны.")
            if len(frame) < request["horizon"]:
                warnings.append(f"В файле осталось {len(frame)} ч: рассчитаны все доступные строки без заполнения отсутствующей погоды.")
        if request["date"] < "2026-02-01":
            warnings.append("Для января используется модель до декабря 2025. Январь уже просмотрен в прежней проверке.")
        request["csv_kind"] = uploaded["kind"]
        return frame, issue, warnings

    def predict(self, payload):
        request = validate_request(payload)
        mode, horizon = request["mode"], request["horizon"]
        bundle = self.evaluation if mode == "check" else self.production
        zone = bundle["config"]["timezone"]
        first = pd.Timestamp(request["date"]).tz_localize(zone)
        issue = first - pd.Timedelta(hours=1)
        targets = pd.date_range(first.tz_convert("UTC"), periods=horizon, freq="h")
        warnings = []
        with self.lock:
            if mode == "csv":
                frame, issue, warnings = self.csv_frame(request)
                first = frame.valid_time.min().tz_convert(zone)
            elif mode == "scenario":
                # Deliberately labelled a hypothetical scenario, not archived weather.
                frame = pd.DataFrame({"valid_time": targets, "issued_at": issue.tz_convert("UTC"),
                                      "turbine_id": request["turbine"], "horizon_hours": range(1, horizon + 1)})
                frame["forecast_offset_days"] = (frame.horizon_hours > 24).astype(int) + 2
                for field, value in request["weather"].items():
                    frame[field] = value
                details = predict_details({**bundle, "use_history": False}, frame)
                frame = pd.concat([frame, details], axis=1)
                frame["actual"] = float("nan")
                # Historical calibration does not describe a user's hypothetical scenario.
                frame[["lower_80", "upper_80"]] = float("nan")
                warnings.append("Сценарий: заданная погода постоянна на всём горизонте. История отключена. Фактическая точность не оценивается.")
            else:
                # Keep both the model-availability guard and causal history filtering.
                weather = self.weather[self.weather.valid_time.isin(targets)]
                frame = forecast(bundle, weather, issue, horizon,
                                 hourly=self.hourly if request["history"] else None)
                frame = frame[frame.turbine_id == request["turbine"]].copy()
                frame = frame.merge(weather[["valid_time", "turbine_id", "forecast_offset_days", *SCENARIO_FIELDS]],
                                    on=["valid_time", "turbine_id", "forecast_offset_days"], validate="one_to_one")
                observed = self.hourly[["valid_time", "turbine_id", "power"]].rename(columns={"power": "actual"})
                frame = frame.merge(observed, on=["valid_time", "turbine_id"], how="left", validate="many_to_one")
                if mode == "check":
                    warnings.append("Повторная проверка января: модель обучена до декабря 2025. Январь уже использовался для отчёта; это не новый независимый тест.")
                else:
                    warnings.append("Прогноз для архивной погоды февраля 2026. Фактических измерений за февраль пока нет.")
                if request["history"] and frame.prediction_mode.eq("weather_only").any():
                    warnings.append("Для части часов нет свежей истории: модель использует только погоду.")
        frame = frame.sort_values("valid_time").reset_index(drop=True)
        frame["time"] = frame.valid_time.dt.tz_convert(zone).dt.strftime("%d.%m %H:%M")
        frame["absolute_error"] = (frame.prediction - frame.actual).abs()
        matched = frame[frame.actual.notna()]
        metrics = scores(matched.actual, matched.prediction) if len(matched) >= 2 else None
        if len(matched) == 1:
            error = float(matched.absolute_error.iloc[0])
            metrics = {"mae": error, "rmse": error, "r2": None}
        if mode in ("check", "csv") and len(matched) != len(frame):
            warnings.append(f"Полные фактические измерения есть для {len(matched)} из {len(frame)} часов. Метрики рассчитаны только по ним.")
        columns = ["time", "valid_time", "issued_at", "turbine_id", "horizon_hours", "prediction",
                   "lower_80", "upper_80", "actual", "absolute_error", "prediction_mode", *SCENARIO_FIELDS]
        rows = json.loads(frame[columns].to_json(orient="records", date_format="iso", double_precision=10))
        if metrics is not None:
            metrics = {key: value if value is not None and math.isfinite(value) else None for key, value in metrics.items()}
        return {"request": request, "timezone": zone, "issued_at": issue.isoformat(),
                "title": f"Турбина {request['turbine']} · {first.strftime('%d.%m.%Y')} · {len(frame)} ч",
                "metrics": metrics, "scored_hours": len(matched), "hours": len(frame),
                "mean_prediction": float(frame.prediction.mean()), "warnings": warnings,
                "history_hours": int(frame.prediction_mode.eq("weather_and_history").sum()), "rows": rows}


def make_handler(app):
    class Handler(BaseHTTPRequestHandler):
        def respond(self, status, payload, content_type="application/json; charset=utf-8"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.respond(200, Path(__file__).with_name("ui.html").read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/status":
                self.respond(200, app.status())
            elif self.path == "/api/csv-template":
                self.respond(200, weather_template(), "text/csv; charset=utf-8")
            else:
                self.respond(404, {"error": "Страница не найдена."})

        def do_POST(self):
            if self.path not in ("/api/predict", "/api/upload-csv"):
                self.respond(404, {"error": "Страница не найдена."})
                return
            if self.headers.get_content_type() != "application/json":
                self.respond(415, {"error": "Ожидается application/json."})
                return
            origin = self.headers.get("Origin")
            port = self.server.server_port
            if origin and origin not in (f"http://127.0.0.1:{port}", f"http://localhost:{port}"):
                self.respond(403, {"error": "Запрос должен быть из локального интерфейса."})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                limit = 24 * 1024 * 1024 if self.path == "/api/upload-csv" else 8192
                if not 0 < length <= limit:
                    raise ValueError("Некорректный размер запроса.")
                payload = json.loads(self.rfile.read(length))
                self.respond(200, app.upload(payload) if self.path == "/api/upload-csv" else app.predict(payload))
            except (ValueError, TypeError, UnicodeDecodeError) as exc:
                self.respond(400, {"error": str(exc)})
            except Exception:
                logging.exception("Local forecast failed")
                self.respond(500, {"error": "Не удалось рассчитать прогноз. Подробности в журнале сервера."})

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        app = ForecastApp()
    except FileNotFoundError as exc:
        parser.error(f"Нет подготовленных данных или модели: {exc.filename}. Сначала выполните prepare, fetch-weather и improve.")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(app))
    print(f"Wind Forecast UI: http://127.0.0.1:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
