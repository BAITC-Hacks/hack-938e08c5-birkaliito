"""Hourly forecasts, normalized farm aggregation, and historical replay."""

import json
from pathlib import Path

import pandas as pd

from .features import as_utc, forecast_table
from .model import predict_bundle


def forecast(bundle, weather, issued_at, horizon=48):
    config = bundle["config"]
    origin = as_utc(issued_at, config["timezone"])
    for key in ("training_max_valid_time", "calibration_max_valid_time"):
        if as_utc(bundle[key], config["timezone"]) + pd.Timedelta(hours=1) > origin:
            raise ValueError(f"Model leakage: {key} contains targets unavailable at issuance")
    frame = forecast_table(weather, origin, horizon, config)
    result = frame[["issued_at", "valid_time", "turbine_id", "horizon_hours", "forecast_offset_days", "source_reference_time_upper_bound", "available_at_upper_bound", "weather_model"]].copy()
    result["prediction"], result["lower_80"], result["upper_80"] = predict_bundle(bundle, frame)
    result["local_time"] = result.valid_time.dt.tz_convert(config["timezone"])
    capacities = {t["id"]: t.get("rated_power_mw") for t in config["turbines"]}
    if all(value is not None and value > 0 for value in capacities.values()):
        result["power_mw"] = result.prediction * result.turbine_id.map(capacities)
        result["energy_mwh"] = result.power_mw  # A one-hour mean MW interval.
    return result


def aggregate_farm(frame, config):
    if frame.duplicated(["issued_at", "valid_time", "turbine_id"]).any():
        raise ValueError("Duplicate turbine forecast rows")
    grouped = frame.groupby(["issued_at", "valid_time"], sort=True)
    if not grouped.turbine_id.nunique().eq(len(config["turbines"])).all():
        raise ValueError("Cannot aggregate incomplete turbine forecasts")
    result = grouped.prediction.mean().rename("mean_normalized_power").to_frame()
    if "power_mw" in frame:
        result["power_mw"] = grouped.power_mw.sum()
        result["energy_mwh"] = grouped.energy_mwh.sum()
        total_capacity = sum(t["rated_power_mw"] for t in config["turbines"])
        result["capacity_weighted_normalized_power"] = result.power_mw / total_capacity
    # Marginal turbine interval bounds cannot be summed into a calibrated farm interval.
    return result.reset_index()


def analysis_report(frame):
    previous = frame.sort_values(["issued_at", "turbine_id", "valid_time"]).groupby(["issued_at", "turbine_id"]).prediction.diff().abs()
    return {"rows": len(frame), "missing_predictions": int(frame.prediction.isna().sum()),
            "min_prediction": float(frame.prediction.min()), "max_prediction": float(frame.prediction.max()),
            "mean_interval_width": float((frame.upper_80 - frame.lower_80).mean()),
            "ramps_over_0_35": int((previous > 0.35).sum()),
            "wide_intervals_over_0_7": int(((frame.upper_80 - frame.lower_80) > 0.7).sum())}


def save_forecast(frame, config, output_dir):
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output / "turbines.csv", index=False)
    aggregate_farm(frame, config).to_csv(output / "farm.csv", index=False)
    (output / "analysis.json").write_text(json.dumps(analysis_report(frame), indent=2), encoding="utf-8")


def replay(bundle, weather, start="2026-02-01", end="2026-02-28", output_dir="outputs/february"):
    config = bundle["config"]
    first = pd.Timestamp(start).normalize()
    last = pd.Timestamp(end).normalize()
    if last < first:
        raise ValueError("end precedes start")
    frames = []
    for day in pd.date_range(first, last, freq="D"):
        origin = (day - pd.Timedelta(hours=1)).tz_localize(config["timezone"])
        # Last issue still produces 48h, including next month's first day.
        frames.append(forecast(bundle, weather, origin, horizon=48))
    all_forecasts = pd.concat(frames, ignore_index=True)
    output = Path(output_dir)
    save_forecast(all_forecasts, config, output)
    begin_utc = as_utc(first, config["timezone"])
    end_utc = as_utc(last + pd.Timedelta(days=1), config["timezone"])
    submission = all_forecasts[(all_forecasts.horizon_hours <= 24) & all_forecasts.valid_time.between(begin_utc, end_utc, inclusive="left")].copy()
    expected_rows = len(pd.date_range(first, last, freq="D")) * 24 * len(config["turbines"])
    if len(submission) != expected_rows or submission.duplicated(["valid_time", "turbine_id"]).any():
        raise ValueError("Replay does not cover every requested hour exactly once")
    submission.to_csv(output / "submission.csv", index=False)
    aggregate_farm(submission, config).to_csv(output / "submission_farm.csv", index=False)
    return submission
