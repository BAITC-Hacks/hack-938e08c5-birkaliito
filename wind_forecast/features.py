"""Features contain only archived forecasts and known calendar information."""

import numpy as np
import pandas as pd

from .weather import VARIABLES, validate_weather


def as_utc(value, timezone):
    stamp = pd.Timestamp(value)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(timezone)
    return stamp.tz_convert("UTC")


def assert_available(frame):
    required = ["valid_time", "issued_at", "available_at_upper_bound"]
    if frame[required].isna().any().any():
        raise ValueError("Missing forecast availability metadata")
    if (frame.available_at_upper_bound > frame.issued_at).any():
        raise ValueError("Weather leakage: source may not have been available at issuance")
    if (frame.valid_time <= frame.issued_at).any():
        raise ValueError("Forecast targets must be after issuance")


def training_table(hourly, weather, timezone):
    frame = weather.merge(hourly[["valid_time", "turbine_id", "power"]], on=["valid_time", "turbine_id"], validate="many_to_one")
    frame = frame.dropna(subset=["power", *VARIABLES]).copy()
    local = frame.valid_time.dt.tz_convert(timezone)
    # Daily issue at 23:00 local time. Day 1: next 00:00..23:00, day 2: following day.
    target_midnight = local.dt.tz_localize(None).dt.normalize()
    origin_naive = target_midnight - pd.to_timedelta((frame.forecast_offset_days - 2) * 24 + 1, unit="h")
    origins = origin_naive.dt.tz_localize(timezone, ambiguous="NaT", nonexistent="NaT")
    frame["issued_at"] = origins.dt.tz_convert("UTC")
    frame = frame.dropna(subset=["issued_at"]).copy()
    frame["horizon_hours"] = (frame.valid_time - frame.issued_at).dt.total_seconds() / 3600
    # Exclude the historical civil-time transition from a fixed 48-hour schedule.
    frame = frame[frame.horizon_hours.between(1, 48)].sort_values(["valid_time", "turbine_id", "forecast_offset_days"]).reset_index(drop=True)
    assert_available(frame)
    return frame


def forecast_table(weather, issued_at, horizon, config):
    validate_weather(weather, config)
    if horizon not in (24, 48):
        raise ValueError("horizon must be 24 or 48")
    origin = as_utc(issued_at, config["timezone"])
    if origin != origin.floor("h"):
        raise ValueError("issued_at must be an exact hour")
    targets = pd.DataFrame({"valid_time": pd.date_range(origin + pd.Timedelta(hours=1), periods=horizon, freq="h")})
    targets["horizon_hours"] = np.arange(1, horizon + 1)
    targets["forecast_offset_days"] = np.where(targets.horizon_hours <= 24, 2, 3)
    ids = pd.DataFrame({"turbine_id": [t["id"] for t in config["turbines"]]})
    wanted = targets.merge(ids, how="cross")
    frame = wanted.merge(weather, on=["valid_time", "turbine_id", "forecast_offset_days"], how="left", validate="one_to_one")
    frame["issued_at"] = origin
    if frame[list(VARIABLES)].isna().any().any():
        raise ValueError("Missing archived weather for requested horizon; fetch required UTC dates first")
    assert_available(frame)
    return frame


def make_features(frame, timezone):
    features = frame[["turbine_id", "forecast_offset_days", *VARIABLES]].astype(float).copy()
    local = frame.valid_time.dt.tz_convert(timezone)
    for name, values, period in (("hour", local.dt.hour, 24), ("year", local.dt.dayofyear, 365.25)):
        features[f"{name}_sin"] = np.sin(2 * np.pi * values / period)
        features[f"{name}_cos"] = np.cos(2 * np.pi * values / period)
    direction = np.deg2rad(frame.wind_direction_100m)
    features["wind_direction_sin"] = np.sin(direction)
    features["wind_direction_cos"] = np.cos(direction)
    features["wind_u"] = frame.wind_speed_100m * np.sin(direction)
    features["wind_v"] = frame.wind_speed_100m * np.cos(direction)
    features["wind_shear"] = frame.wind_speed_100m - frame.wind_speed_10m
    features["air_density_proxy"] = frame.surface_pressure * 100 / (287.05 * (frame.temperature_2m + 273.15))
    features["wind_power_proxy"] = features.air_density_proxy * frame.wind_speed_100m.clip(0, 30) ** 3
    return features.drop(columns="wind_direction_100m")
