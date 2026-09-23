import copy
import io
import json
import threading
from collections import OrderedDict

import numpy as np
import pandas as pd
import pytest

from wind_forecast.features import forecast_table, make_features
from wind_forecast.model import estimator
from wind_forecast.ui import ForecastApp, validate_request
from wind_forecast.uploads import parse_upload, weather_template


@pytest.fixture
def app(config, weather):
    frame = forecast_table(weather, "2026-01-31T23:00", 48, config)
    features = make_features(frame, config["timezone"])
    model = estimator(2, trees=5)
    model.fit(features, np.linspace(0.1, 0.8, len(features)))
    bundle = {"config": config, "model": model, "features": list(features),
              "training_max_valid_time": "2026-01-31T17:00Z", "calibration_max_valid_time": "2025-12-30T17:00Z",
              "interval_offsets": {f"{t}:{d}": [-0.2, 0.2] for t in (1, 2) for d in (2, 3)}}
    instance = ForecastApp.__new__(ForecastApp)
    instance.production = bundle
    instance.evaluation = copy.deepcopy(bundle)
    instance.evaluation["training_max_valid_time"] = "2025-11-30T18:00Z"
    instance.weather = weather
    instance.hourly = weather[["valid_time", "turbine_id"]].drop_duplicates().copy()
    instance.hourly = instance.hourly[instance.hourly.valid_time < pd.Timestamp("2026-01-31T19:00Z")]
    instance.hourly["power"] = np.linspace(0.1, 0.8, len(instance.hourly))
    instance.hourly["wind_speed"] = 7.0
    instance.hourly["temperature"] = 10.0
    instance.lock = threading.Lock()
    instance.uploads = OrderedDict()
    return instance


def test_january_ui_uses_earlier_model_and_scores_only_available_actual(app):
    response = app.predict({"mode": "check", "date": "2026-01-31", "turbine": 2, "horizon": 48})
    assert response["scored_hours"] == 24
    assert response["hours"] == 48
    assert response["metrics"]["mae"] >= 0
    errors = [abs(row["prediction"] - row["actual"]) for row in response["rows"] if row["actual"] is not None]
    assert response["metrics"]["hit_rate_10pp"] == pytest.approx(np.mean(np.asarray(errors) <= .10 + 1e-12))
    assert all(row["turbine_id"] == 2 for row in response["rows"])
    assert all(row["actual"] is None for row in response["rows"][24:])
    # The UI must retain the forecast time guard if a wrong artifact is selected.
    app.evaluation = app.production
    with pytest.raises(ValueError, match="Model leakage"):
        app.predict({"mode": "check", "date": "2026-01-31"})


def test_ui_future_forecasts_have_no_invented_metrics_and_are_json_serializable(app):
    response = app.predict({"mode": "forecast", "date": "2026-02-02"})
    assert response["metrics"] is None
    assert response["scored_hours"] == 0
    assert len(response["rows"]) == 48
    json.dumps(response, allow_nan=False)


def test_hypothetical_weather_never_shows_actual_scores_or_calibrated_band(app):
    request = {"mode": "scenario", "date": "2026-02-01", "horizon": 24,
               "weather": {"wind_speed_10m": 5, "wind_speed_100m": 8, "wind_direction_100m": 270,
                           "temperature_2m": 10, "surface_pressure": 930}}
    response = app.predict(request)
    assert response["metrics"] is None
    assert response["history_hours"] == 0
    assert all(row["lower_80"] is None and row["actual"] is None for row in response["rows"])
    request["weather"]["wind_speed_100m"] = float("nan")
    with pytest.raises(ValueError, match="wind_speed_100m"):
        validate_request(request)


def test_uploaded_weather_labels_change_metrics_but_never_predictions(app):
    source = pd.read_csv(io.StringIO(weather_template().decode('utf-8-sig')))
    source["actual_power"] = 0.1
    info = app.upload({"csv_text": source.to_csv(index=False)})
    request = {"mode": "csv", "date": "2026-02-01", "upload_id": info["upload_id"], "horizon": 48}
    first = app.predict(request)
    source["actual_power"] = 0.9
    updated = app.upload({"csv_text": source.to_csv(index=False)})
    second = app.predict({**request, "upload_id": updated["upload_id"]})
    assert [r["prediction"] for r in first["rows"]] == [r["prediction"] for r in second["rows"]]
    assert first["metrics"]["mae"] != second["metrics"]["mae"]
    assert first["scored_hours"] == 48
    assert first["rows"][0]["valid_time"].startswith("2026-01-31T19:00")
    assert all(row["lower_80"] is None for row in first["rows"])


def test_csv_turbine_uses_uploaded_actual_instead_of_bundled_actual(app):
    times = pd.date_range("2026-01-30", periods=2 * 24 * 6, freq="10min")
    source = pd.DataFrame({"timestamp": times, "power": 0.12, "wind_speed": 7, "temperature": 10})
    info = app.upload({"csv_text": source.to_csv(index=False)})
    assert info["kind"] == "scada"
    response = app.predict({"mode": "csv", "date": "2026-01-31", "turbine": 2,
                            "horizon": 48, "upload_id": info["upload_id"]})
    assert response["scored_hours"] == 24
    assert all(row["actual"] == pytest.approx(0.12) for row in response["rows"][:24])
    assert all(row["actual"] is None for row in response["rows"][24:])


def test_csv_rejects_gaps_and_weather_issued_after_forecast_origin(app):
    source = pd.read_csv(io.StringIO(weather_template().decode('utf-8-sig')))
    info = app.upload({"csv_text": source.drop(index=3).to_csv(index=False)})
    with pytest.raises(ValueError, match="пропуски часов"):
        app.predict({"mode": "csv", "date": "2026-02-01", "upload_id": info["upload_id"]})
    source["issued_at"] = "2026-01-31 23:30"  # Even sub-hour issuance must be rejected, not truncated.
    with pytest.raises(ValueError, match="начало часа"):
        app.upload({"csv_text": source.to_csv(index=False)})
    source["issued_at"] = "2026-02-01 00:00"
    source.loc[0, "issued_at"] = "2026-01-31 23:00"
    info = app.upload({"csv_text": source.to_csv(index=False)})
    with pytest.raises(ValueError, match="позже момента"):
        app.predict({"mode": "csv", "date": "2026-02-01", "upload_id": info["upload_id"]})


def test_semicolon_decimal_comma_bom_and_bad_values_are_handled():
    header = "\ufeffvalid_time;wind_speed_10m;wind_speed_100m;wind_direction_100m;temperature_2m;surface_pressure\n"
    row = "2026-02-01 00:00;5,5;8,5;270;-2,5;930\n"
    result = parse_upload(header + row, "Asia/Almaty")
    assert result["frame"].wind_speed_100m.iloc[0] == 8.5
    with pytest.raises(ValueError, match="повторяется час"):
        parse_upload(header + row + row, "Asia/Almaty")
    with pytest.raises(ValueError, match="wind_speed_100m"):
        parse_upload(header + row.replace("8,5", "NaN"), "Asia/Almaty")
    with pytest.raises(ValueError, match="число значений"):
        parse_upload(header + row.strip() + ";unexpected\n", "Asia/Almaty")


def test_csv_with_explicit_turbine_id_is_not_relabelled_and_short_file_is_kept(app):
    source = pd.read_csv(io.StringIO(weather_template().decode('utf-8-sig'))).head(3)
    source["turbine_id"] = 2
    info = app.upload({"csv_text": source.to_csv(index=False)})
    with pytest.raises(ValueError, match="нет погоды"):
        app.predict({"mode": "csv", "date": "2026-02-01", "turbine": 1, "upload_id": info["upload_id"]})
    result = app.predict({"mode": "csv", "date": "2026-02-01", "turbine": 2, "upload_id": info["upload_id"]})
    assert result["hours"] == 3
    assert result["metrics"] is None
    assert all(row["turbine_id"] == 2 for row in result["rows"])
    json.dumps(result, allow_nan=False)
