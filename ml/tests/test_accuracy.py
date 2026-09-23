import joblib
import numpy as np
import pandas as pd
import pytest

from wind_forecast.accuracy import CENTERS, WindowRegressor, accuracy_scores
from wind_forecast.features import forecast_table, make_features
from wind_forecast.forecast import forecast
from wind_forecast.history import combine_features, history_features
from wind_forecast.model import predict_details
from wind_forecast.weather import VARIABLES


def test_hit_rate_uses_fixed_tolerance_and_includes_boundaries():
    result = accuracy_scores([0, .4, 1, .4], [.1, .3, .9, .501])
    assert result["hit_rate_10pp"] == .75
    assert result["hits_10pp"] == 3
    assert result["rows"] == 4
    with pytest.raises(ValueError):
        accuracy_scores([0, np.nan], [0, 0])


def test_window_events_overlap_and_cover_normalized_endpoints():
    labels = WindowRegressor.labels([0, .15, .5, 1])
    assert labels[0, 0] == 1
    assert labels[-1, -1] == 1
    assert labels[1].sum() > 1
    with pytest.raises(ValueError):
        WindowRegressor.labels([1.01])


def test_ensemble_forecast_rejects_an_archive_for_only_one_model(config, weather):
    bundle = {"config": config, "additional_weather_columns": [f"icon_{name}" for name in VARIABLES]}
    with pytest.raises(ValueError, match="additional ICON"):
        forecast(bundle, weather, "2026-01-31T23:00")


@pytest.mark.parametrize("with_icon", [False, True])
def test_window_model_roundtrip_and_future_history_invariance(tmp_path, config, weather, with_icon):
    frame = forecast_table(weather, "2026-01-31T23:00", 48, config)
    extra = [f"icon_{name}" for name in VARIABLES] if with_icon else []
    for name in extra:
        frame[name] = frame[name.removeprefix("icon_")] + .5
    base = make_features(frame, config["timezone"])
    hours = pd.date_range("2026-01-20", "2026-02-04", freq="h", tz="UTC")
    hourly = pd.DataFrame({"valid_time": hours, "turbine_id": 1,
                           "power": .4, "wind_speed": 5., "temperature": 2.})
    hist = history_features(hourly, frame, config["history"])
    extended = combine_features(base, frame, hist)
    target = np.linspace(0, 1, len(base))
    bundle = {"config": config, "model": WindowRegressor(trees=3).fit(base, target),
              "features": list(base), "history_model": WindowRegressor(trees=3).fit(extended, target),
              "history_features": list(extended), "history_weight": 1.,
              "additional_weather_columns": extra,
              "interval_offsets": {f"{t}:{d}": [-.2, .2] for t in (1, 2) for d in (2, 3)}}
    path = tmp_path / "model.joblib"
    joblib.dump(bundle, path)
    before = predict_details(joblib.load(path), frame, hourly)
    # Even the row beginning at issue time is unfinished and must not be read.
    hourly.loc[hourly.valid_time >= frame.issued_at.min(), ["power", "wind_speed", "temperature"]] = 999
    after = predict_details(bundle, frame, hourly)
    pd.testing.assert_frame_equal(before, after)
    assert before.prediction.isin(CENTERS).all()
    assert set(before.prediction_mode) == {"weather_only", "weather_and_history"}
    if with_icon:
        missing_extra = predict_details(bundle, frame.drop(columns=extra), hourly)
        assert missing_extra.prediction.isin(CENTERS).all()
