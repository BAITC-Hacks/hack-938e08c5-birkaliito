import copy

import joblib
import numpy as np
import pandas as pd
import pytest

from wind_forecast.features import assert_available, forecast_table, make_features, training_table
from wind_forecast.forecast import aggregate_farm, forecast, replay
from wind_forecast.model import estimator, persistence_predictions
from wind_forecast.weather import fetch_json


def small_bundle(config, weather):
    frame = forecast_table(weather, "2026-01-31T23:00", 48, config)
    features = make_features(frame, config["timezone"])
    model = estimator(2, trees=5)
    model.fit(features, np.linspace(0.1, 0.8, len(features)))
    return {"config": config, "model": model, "features": list(features),
            "training_max_valid_time": "2026-01-31T17:00Z", "calibration_max_valid_time": "2025-12-30T17:00Z",
            "interval_offsets": {f"{t}:{d}": [-0.2, 0.2] for t in (1, 2) for d in (2, 3)}}


def test_weather_offsets_cover_48_hours_before_issue(config, weather):
    frame = forecast_table(weather, "2026-01-31T23:00", 48, config)
    assert len(frame) == 96
    assert frame.groupby("turbine_id").size().eq(48).all()
    assert (frame.available_at_upper_bound <= frame.issued_at).all()
    assert frame[frame.horizon_hours <= 24].forecast_offset_days.eq(2).all()
    assert frame[frame.horizon_hours > 24].forecast_offset_days.eq(3).all()
    assert make_features(frame, config["timezone"]).isna().sum().sum() == 0


def test_future_weather_is_rejected(config, weather):
    frame = forecast_table(weather, "2026-01-31T23:00", 48, config)
    frame.loc[0, "available_at_upper_bound"] = frame.issued_at.iloc[0] + pd.Timedelta(hours=1)
    with pytest.raises(ValueError, match="Weather leakage"):
        assert_available(frame)


def test_missing_weather_fails_closed(config, weather):
    weather = weather[weather.valid_time != pd.Timestamp("2026-02-01T00:00Z")]
    with pytest.raises(ValueError, match="Missing archived weather"):
        forecast_table(weather, "2026-01-31T23:00", 48, config)


def test_wrong_provider_rejected(config, weather):
    weather["weather_model"] = "different_model"
    with pytest.raises(ValueError, match="Weather model"):
        forecast_table(weather, "2026-01-31T23:00", 48, config)


def test_targets_never_become_features(config, weather):
    hourly = weather[["valid_time", "turbine_id"]].drop_duplicates().assign(power=0.2)
    first = training_table(hourly, weather, config["timezone"])
    changed = training_table(hourly.assign(power=0.9), weather, config["timezone"])
    pd.testing.assert_frame_equal(make_features(first, config["timezone"]), make_features(changed, config["timezone"]))
    assert "power" not in make_features(first, config["timezone"])


def test_persistence_only_uses_completed_hours():
    hourly = pd.DataFrame({"valid_time": pd.date_range("2026-01-31T20:00Z", periods=4, freq="h"), "power": [0.1, 0.2, 0.8, 0.9], "turbine_id": 1})
    targets = pd.DataFrame({"issued_at": [pd.Timestamp("2026-01-31T22:00Z")], "turbine_id": 1})
    assert persistence_predictions(hourly, targets)[0] == pytest.approx(0.2)


def test_model_with_future_targets_cannot_predict_past(config, weather):
    bundle = small_bundle(config, weather)
    bundle["training_max_valid_time"] = "2026-01-31T18:00Z"
    with pytest.raises(ValueError, match="Model leakage"):
        forecast(bundle, weather, "2026-01-31T23:00")


def test_serialization_and_full_february_replay(tmp_path, config, weather):
    bundle = small_bundle(config, weather)
    path = tmp_path / "model.joblib"
    joblib.dump(bundle, path)
    loaded = joblib.load(path)
    expected = forecast(bundle, weather, "2026-01-31T23:00")
    actual = forecast(loaded, weather, "2026-01-31T23:00")
    pd.testing.assert_frame_equal(expected, actual)
    submission = replay(loaded, weather, output_dir=tmp_path / "replay")
    assert len(submission) == 28 * 24 * 2
    assert submission.prediction.between(0, 1).all()
    assert (submission.lower_80 <= submission.prediction).all()
    assert (submission.upper_80 >= submission.prediction).all()
    assert len(pd.read_csv(tmp_path / "replay" / "submission_farm.csv")) == 672


def test_farm_uses_capacities_only_when_provided(config, weather):
    bundle = small_bundle(config, weather)
    result = forecast(bundle, weather, "2026-01-31T23:00")
    assert "energy_mwh" not in result
    capacities = copy.deepcopy(config)
    capacities["turbines"][0]["rated_power_mw"] = 2
    capacities["turbines"][1]["rated_power_mw"] = 3
    bundle["config"] = capacities
    result = forecast(bundle, weather, "2026-01-31T23:00")
    farm = aggregate_farm(result, capacities)
    np.testing.assert_allclose(farm.power_mw / 5, farm.capacity_weighted_normalized_power)
    with pytest.raises(ValueError, match="incomplete"):
        aggregate_farm(result.iloc[1:], capacities)


def test_offline_mode_never_accesses_network(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Unexpected network request")
    monkeypatch.setattr("wind_forecast.weather.urlopen", forbidden)
    with pytest.raises(FileNotFoundError, match="Offline weather cache"):
        fetch_json({"test": 1}, tmp_path, cache_only=True)


def test_agent_recomputes_only_changed_inputs(tmp_path, monkeypatch, config, weather):
    from wind_forecast.agent import run_agent
    path = tmp_path / "model.joblib"
    joblib.dump(small_bundle(config, weather), path)
    monkeypatch.setattr("wind_forecast.agent.fetch_archive", lambda *args, **kwargs: weather.copy())
    assert run_agent(path, "2026-01-31T23:00", tmp_path / "agent")["status"] == "updated"
    assert run_agent(path, "2026-01-31T23:00", tmp_path / "agent")["status"] == "unchanged"
    weather.loc[0, "wind_speed_100m"] += 1
    assert run_agent(path, "2026-01-31T23:00", tmp_path / "agent")["status"] == "updated"
