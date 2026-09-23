import numpy as np
import pandas as pd
import pytest

from wind_forecast.features import forecast_table, make_features
from wind_forecast.history import combine_features, history_features
from wind_forecast.model import estimator
from wind_forecast.validation import chronological_fold


def observations(start="2025-01-01", periods=240):
    return pd.DataFrame({"valid_time": pd.date_range(start, periods=periods, freq="h", tz="UTC"),
                         "turbine_id": 1, "power": np.arange(periods) / periods,
                         "wind_speed": 7.0, "temperature": 15.0})


def test_history_uses_completed_hours_and_ignores_future_labels():
    hourly = observations()
    issued = hourly.valid_time.iloc[100]
    frame = pd.DataFrame({"issued_at": [issued, issued + pd.Timedelta(hours=2)], "turbine_id": 1})
    original = history_features(hourly, frame)
    changed = hourly.copy()
    changed.loc[changed.valid_time >= issued + pd.Timedelta(hours=2), ["power", "wind_speed", "temperature"]] = 999
    pd.testing.assert_frame_equal(original, history_features(changed, frame))
    assert original.observed_power_last.iloc[0] == pytest.approx(hourly.power.iloc[99])
    assert original.history_age_hours.eq(0).all()


def test_history_is_specific_to_each_issue_not_latest_available_row():
    hourly = observations()
    origin = hourly.valid_time.iloc[100]
    frame = pd.DataFrame({"issued_at": [origin, origin + pd.Timedelta(hours=48)], "turbine_id": 1})
    original = history_features(hourly, frame)
    hourly.loc[hourly.valid_time >= origin, "power"] = 0.99
    updated = history_features(hourly, frame)
    pd.testing.assert_series_equal(original.iloc[0], updated.iloc[0])
    assert updated.observed_power_last.iloc[1] == pytest.approx(0.99)


def test_hourly_gaps_remain_real_gaps_in_lags():
    hourly = observations()
    origin = hourly.valid_time.iloc[100]
    hourly = hourly.drop(index=96)
    features = history_features(hourly, pd.DataFrame({"issued_at": [origin], "turbine_id": 1}))
    assert pd.isna(features.observed_power_lag_3h.iloc[0])
    assert features.history_count_24h.iloc[0] == 23


def test_history_staleness_and_coverage_disable_observation_model():
    hourly = observations(periods=100)
    latest = hourly.valid_time.max() + pd.Timedelta(hours=1)
    frame = pd.DataFrame({"issued_at": [latest, latest + pd.Timedelta(hours=4)], "turbine_id": 1})
    result = history_features(hourly, frame)
    assert result.history_usable.tolist() == [True, False]
    sparse = hourly.iloc[-2:]
    assert not history_features(sparse, frame).history_usable.any()
    assert not history_features(None, frame).history_usable.any()


def test_turbine_histories_are_not_mixed():
    first = observations()
    second = first.assign(turbine_id=2, power=0.99)
    origin = first.valid_time.iloc[100]
    frame = pd.DataFrame({"issued_at": [origin, origin], "turbine_id": [1, 2]})
    result = history_features(pd.concat([first, second]), frame)
    assert result.observed_power_last.iloc[0] == pytest.approx(first.power.iloc[99])
    assert result.observed_power_last.iloc[1] == pytest.approx(0.99)


def test_training_and_stopping_labels_precede_validation_issuance():
    times = pd.date_range("2024-01-01", "2025-02-01", freq="h", tz="UTC")
    table = pd.DataFrame({"valid_time": times, "issued_at": times - pd.Timedelta(hours=48)})
    fold = chronological_fold(table, "2025-01-01", "2025-02-01", "UTC")
    assert (table.loc[fold["train"], "valid_time"] + pd.Timedelta(hours=1) <= fold["first_issue"]).all()
    assert (table.loc[fold["core"], "valid_time"] + pd.Timedelta(hours=1) <= fold["inner_cutoff"]).all()
    assert (table.loc[fold["stopping"], "issued_at"] >= fold["inner_cutoff"]).all()
    assert not (fold["train"] & fold["validation"]).any()
    assert not (fold["core"] & fold["stopping"]).any()


def test_hybrid_forecast_falls_back_without_recent_measurements(config, weather):
    from wind_forecast.forecast import forecast
    frame = forecast_table(weather, "2026-01-31T23:00", 48, config)
    hourly = observations(start="2026-01-20", periods=400)
    hourly = pd.concat([hourly, hourly.assign(turbine_id=2)], ignore_index=True)
    base = make_features(frame, config["timezone"])
    extended = combine_features(base, frame, history_features(hourly, frame, config["history"]))
    weather_model = estimator(2, 5).fit(base, np.full(len(base), 0.2))
    history_model = estimator(2, 5).fit(extended, np.full(len(base), 0.8))
    bundle = {"model": weather_model, "history_model": history_model, "use_history": True,
              "config": config, "features": list(base), "history_features": list(extended),
              "training_max_valid_time": "2026-01-01T00:00Z", "calibration_max_valid_time": "2026-01-02T00:00Z",
              "interval_offsets": {f"{t}:{d}": [-0.1, 0.1] for t in (1, 2) for d in (2, 3)}}
    fresh = forecast(bundle, weather, "2026-01-31T23:00", hourly=hourly)
    absent = forecast(bundle, weather, "2026-01-31T23:00")
    assert fresh.prediction_mode.eq("weather_and_history").all()
    assert absent.prediction_mode.eq("weather_only").all()
    np.testing.assert_allclose(fresh.prediction, 0.8, atol=1e-6)
    np.testing.assert_allclose(absent.prediction, 0.2, atol=1e-6)
    ancient = hourly[hourly.valid_time < pd.Timestamp("2026-01-30T00:00Z")]
    stale = forecast(bundle, weather, "2026-01-31T23:00", hourly=ancient)
    assert stale.prediction_mode.eq("weather_only").all()
    bundle["history_weight"] = 0.25
    blended = forecast(bundle, weather, "2026-01-31T23:00", hourly=hourly)
    np.testing.assert_allclose(blended.prediction, 0.35, atol=1e-6)


def test_blend_selection_uses_validation_errors():
    from wind_forecast.experiments import select_history_weight
    predictions = pd.DataFrame({"fold": ["a", "a", "b", "b"], "power": [0.5, 0.5, 0.5, 0.5],
                                "weather_prediction": [0.3, 0.7, 0.3, 0.7], "history_prediction": [0.7, 0.3, 0.7, 0.3]})
    best, trials = select_history_weight(predictions)
    assert best["history_weight"] == 0.5
    assert best["mean_mae"] == 0
    assert len(trials) == 5
