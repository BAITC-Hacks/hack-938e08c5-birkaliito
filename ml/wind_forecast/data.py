"""Strict ingestion; missing SCADA intervals are never synthesized as targets."""

import json
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

COLUMN_MAP = {
    "Статистическое время": "timestamp",
    "Средняя скорость ветра(m/s)": "wind_speed",
    "Нормализованная активная мощность": "power",
    "Средняя температура окружающей среды(°C)": "temperature",
}


def read_config(path="config.json"):
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    ZoneInfo(config["timezone"])
    ids = [t["id"] for t in config["turbines"]]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError("Turbine IDs must be nonempty and unique")
    if not 0 <= config["weather_publication_delay_hours"] <= 24:
        raise ValueError("Weather publication allowance must lie between 0 and 24h")
    for turbine in config["turbines"]:
        if not -90 <= turbine["latitude"] <= 90 or not -180 <= turbine["longitude"] <= 180:
            raise ValueError("Invalid turbine coordinates")
        capacity = turbine.get("rated_power_mw")
        if capacity is not None and (not np.isfinite(capacity) or capacity <= 0):
            raise ValueError("rated_power_mw must be positive or null")
    return config


def load_turbine(path, turbine_id, timezone, min_samples=6):
    if not 1 <= min_samples <= 6:
        raise ValueError("min_samples must be between 1 and 6")
    raw = pd.read_csv(path, encoding="utf-8-sig").rename(columns=COLUMN_MAP)
    required = ["timestamp", "wind_speed", "power", "temperature"]
    if set(required) - set(raw):
        raise ValueError(f"Unexpected CSV columns: {list(raw.columns)}")
    times = pd.to_datetime(raw["timestamp"], format="mixed", errors="raise")
    if times.duplicated().any():
        raise ValueError(f"Duplicate timestamps in {path}")
    if ((times.dt.minute % 10 != 0) | (times.dt.second != 0)).any():
        raise ValueError("SCADA timestamps must lie on the 10-minute grid")
    localized = times.dt.tz_localize(timezone, ambiguous="NaT", nonexistent="NaT")
    clean = raw[required[1:]].apply(pd.to_numeric, errors="coerce")
    valid = (
        np.isfinite(clean).all(axis=1)
        & clean.power.between(0, 1)
        & clean.wind_speed.between(0, 60)
        & clean.temperature.between(-80, 65)
        & localized.notna()
    )
    clean = clean.loc[valid].set_index(pd.DatetimeIndex(localized.loc[valid])).sort_index()
    if clean.empty:
        raise ValueError(f"No valid observations in {path}")
    clean.index = clean.index.tz_convert("UTC")
    hourly = clean.resample("h").mean()
    hourly["sample_count"] = clean.power.resample("h").count()
    hourly.loc[hourly.sample_count < min_samples, ["power", "wind_speed", "temperature"]] = np.nan
    hourly.index.name = "valid_time"
    hourly = hourly.reset_index()
    hourly["turbine_id"] = turbine_id
    profile = {
        "turbine_id": turbine_id, "rows": len(raw), "invalid_rows": int((~valid).sum()),
        "ambiguous_or_nonexistent_time_rows": int(localized.isna().sum()),
        "first_local_time": str(times.min()), "last_local_time": str(times.max()),
        "expected_10min_rows": int((times.max() - times.min()) / pd.Timedelta(minutes=10)) + 1,
        "valid_hours": int(hourly.power.notna().sum()),
        "missing_or_incomplete_hours": int(hourly.power.isna().sum()),
    }
    return hourly, profile


def prepare_data(paths, config, output_dir="data/processed"):
    frames, profiles = [], []
    for turbine, path in zip(config["turbines"], paths, strict=True):
        frame, profile = load_turbine(path, turbine["id"], config["timezone"], config["min_samples_per_hour"])
        frames.append(frame)
        profiles.append(profile)
    result = pd.concat(frames, ignore_index=True).sort_values(["valid_time", "turbine_id"])
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    result.to_csv(output / "hourly.csv", index=False)
    (output / "data_quality.json").write_text(json.dumps(profiles, indent=2), encoding="utf-8")
    return result, profiles


def read_hourly(path="data/processed/hourly.csv"):
    frame = pd.read_csv(path)
    frame["valid_time"] = pd.to_datetime(frame["valid_time"], utc=True)
    return frame
