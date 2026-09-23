"""Archived GFS forecasts, with conservative, explicit availability bounds.

Previous Runs supplies fixed-lead values, not exact run IDs. The latest source
reference time is valid_time - offset; we add a publication allowance and check
that this upper bound precedes issuance. Offsets 2/3 give >=24h of margin.
"""

import hashlib
import json
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

ENDPOINT = "https://previous-runs-api.open-meteo.com/v1/forecast"
VARIABLES = ("wind_speed_10m", "wind_speed_100m", "wind_direction_100m", "temperature_2m", "surface_pressure")


def fetch_json(params, cache_dir, refresh=False, cache_only=False):
    url = ENDPOINT + "?" + urlencode(params)
    key = hashlib.sha256(url.encode()).hexdigest()
    cache = Path(cache_dir) / f"{key}.json"
    if cache.exists() and not refresh:
        return json.loads(cache.read_text(encoding="utf-8"))["response"]
    if cache_only:
        raise FileNotFoundError(f"Offline weather cache is missing: {cache}")
    for attempt in range(4):
        try:
            with urlopen(Request(url, headers={"User-Agent": "HackAlem-Wind/0.1"}), timeout=90) as response:
                payload = json.load(response)
            break
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise RuntimeError(f"Weather API HTTP {exc.code}: {detail}") from exc
            time.sleep(10 * (attempt + 1))
        except (URLError, TimeoutError):
            if attempt == 3:
                raise
            time.sleep(2 * (attempt + 1))
    cache.parent.mkdir(parents=True, exist_ok=True)
    envelope = {"url": url, "retrieved_at": pd.Timestamp.now(tz="UTC").isoformat(), "response": payload}
    temporary = cache.with_suffix(".tmp")
    temporary.write_text(json.dumps(envelope), encoding="utf-8")
    temporary.replace(cache)
    return payload


def fetch_archive(config, start, end, output="data/weather/archive.csv", refresh=False, cache_only=False):
    start, end = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    if end < start:
        raise ValueError("end precedes start")
    frames = []
    current = start
    while current <= end:
        chunk_end = min(current + pd.offsets.MonthEnd(0), end)
        params = {
            "latitude": ",".join(str(t["latitude"]) for t in config["turbines"]),
            "longitude": ",".join(str(t["longitude"]) for t in config["turbines"]),
            "start_date": current.strftime("%Y-%m-%d"), "end_date": chunk_end.strftime("%Y-%m-%d"),
            "hourly": ",".join(f"{v}_previous_day{d}" for d in (2, 3) for v in VARIABLES),
            "models": config["weather_model"], "wind_speed_unit": "ms", "timezone": "UTC",
        }
        print(f"Weather: {params['start_date']}..{params['end_date']}", flush=True)
        payload = fetch_json(params, Path(output).parent / "cache", refresh, cache_only)
        locations = payload if isinstance(payload, list) else [payload]
        if len(locations) != len(config["turbines"]):
            raise ValueError("Weather API returned wrong number of locations")
        for turbine, location in zip(config["turbines"], locations, strict=True):
            hourly = location["hourly"]
            units = location["hourly_units"]
            if any(units.get(f"wind_speed_100m_previous_day{day}") != "m/s" for day in (2, 3)):
                raise ValueError("Weather wind-speed units must be m/s")
            for day in (2, 3):
                frame = pd.DataFrame({v: hourly[f"{v}_previous_day{day}"] for v in VARIABLES})
                frame["valid_time"] = pd.to_datetime(hourly["time"], utc=True)
                frame["turbine_id"] = turbine["id"]
                frame["forecast_offset_days"] = day
                frame["source_reference_time_upper_bound"] = frame.valid_time - pd.Timedelta(days=day)
                frame["available_at_upper_bound"] = frame.source_reference_time_upper_bound + pd.Timedelta(hours=config["weather_publication_delay_hours"])
                frame["weather_model"] = config["weather_model"]
                frames.append(frame)
        current = chunk_end + pd.Timedelta(days=1)
        if current <= end:
            time.sleep(1)
    result = pd.concat(frames, ignore_index=True)
    if result[list(VARIABLES)].isna().all().any():
        raise ValueError("An entire weather variable is missing; verify archive coverage/model")
    target = Path(output)
    target.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(target, index=False)
    return result


def read_weather(path="data/weather/archive.csv"):
    frame = pd.read_csv(path)
    for column in ("valid_time", "source_reference_time_upper_bound", "available_at_upper_bound"):
        frame[column] = pd.to_datetime(frame[column], utc=True)
    keys = ["valid_time", "turbine_id", "forecast_offset_days"]
    if frame.duplicated(keys).any():
        raise ValueError("Duplicate archived forecasts")
    return frame


def validate_weather(frame, config):
    if frame.empty or set(frame.weather_model) != {config["weather_model"]}:
        raise ValueError("Weather model does not match configuration/trained artifact")
    if not frame.forecast_offset_days.isin([2, 3]).all():
        raise ValueError("Only 48h/72h archived weather offsets are supported")
    reference = frame.valid_time - pd.to_timedelta(frame.forecast_offset_days, unit="D")
    if not frame.source_reference_time_upper_bound.eq(reference).all():
        raise ValueError("Invalid weather reference-time metadata")
    required_availability = reference + pd.Timedelta(hours=config["weather_publication_delay_hours"])
    if (frame.available_at_upper_bound < required_availability).any():
        raise ValueError("Weather publication allowance is missing or too small")
