"""Separate conditional-power diagnostic; measured future wind is NOT a forecast."""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wind_forecast.accuracy import accuracy_scores
from wind_forecast.data import read_config, read_hourly
from wind_forecast.features import as_utc
from wind_forecast.weather import read_weather


def main():
    zone = read_config()["timezone"]
    hourly = read_hourly().dropna(subset=["power", "wind_speed"])
    cutoff, start, end = [as_utc(s, zone) for s in ("2025-12-01", "2026-01-01", "2026-02-01")]
    curves, frames = {}, []
    for turbine, history in hourly.groupby("turbine_id"):
        train = history[history.valid_time + pd.Timedelta(hours=1) <= cutoff]
        check = history[history.valid_time.between(start, end, inclusive="left")].copy()
        curve = IsotonicRegression(y_min=0, y_max=1, out_of_bounds="clip").fit(train.wind_speed, train.power)
        curves[turbine] = curve
        check["oracle_prediction"] = curve.predict(check.wind_speed)
        frames.append(check)
    check = pd.concat(frames).reset_index(drop=True)
    result = {"warning": "Conditional-power diagnostic with FUTURE MEASURED WIND, not operational forecast accuracy",
              "fit_completed_by": str(cutoff), "oracle_january": accuracy_scores(check.power, check.oracle_prediction),
              "weather_error_january": {}, "constant_0_1_january": accuracy_scores(check.power, np.full(len(check), .1)),
              "timezone": zone, "lag_diagnostic_2025": {}}
    for source, path in (("gfs", "data/weather/archive.csv"), ("icon", "data/weather/icon/archive.csv")):
        weather = read_weather(path)
        joined = weather.merge(check[["valid_time", "turbine_id", "wind_speed"]], on=["valid_time", "turbine_id"])
        joined = joined.dropna(subset=["wind_speed_100m"])
        error = joined.wind_speed_100m - joined.wind_speed
        result["weather_error_january"][source] = {"mae_ms": float(error.abs().mean()), "bias_ms": float(error.mean()),
                                                    "correlation": float(joined.wind_speed_100m.corr(joined.wind_speed)),
                                                    "rows": len(joined),
                                                    "caveat": "NWP 100m vs SCADA sensor of unconfirmed height; not pure NWP error"}
        past = hourly[hourly.valid_time.between(as_utc("2025-01-01", zone), cutoff, inclusive="left")]
        first_day = weather[weather.forecast_offset_days == 2][["valid_time", "turbine_id", "wind_speed_100m"]]
        lags = []
        for lag in range(-12, 13):
            shifted = first_day.assign(valid_time=first_day.valid_time + pd.Timedelta(hours=lag))
            aligned = past.merge(shifted, on=["valid_time", "turbine_id"]).dropna(subset=["wind_speed_100m"])
            lags.append({"weather_timestamp_shift_hours": lag, "correlation": float(aligned.wind_speed.corr(aligned.wind_speed_100m))})
        result["lag_diagnostic_2025"][source] = lags
    # Sensitivity simulation: this assumes unbiased IID Gaussian wind errors,
    # which is not a forecast model and does not describe real weather errors.
    rng = np.random.default_rng(42)
    sensitivity = []
    for sigma in (0., .5, 1., 1.5, 2., 3.):
        actual, predictions = [], []
        for turbine, group in check.groupby("turbine_id"):
            wind = group.wind_speed.to_numpy()[:, None] + rng.normal(0, sigma, (len(group), 100))
            pred = curves[turbine].predict(wind.clip(0).ravel())
            predictions.extend(pred)
            actual.extend(np.repeat(group.power.to_numpy(), 100))
        sensitivity.append({"assumed_wind_error_std_ms": sigma, **accuracy_scores(actual, predictions)})
    result["hypothetical_iid_wind_noise"] = sensitivity
    output = Path("reports/accuracy/diagnostic.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "lag_diagnostic_2025"}, indent=2))


if __name__ == "__main__":
    main()
