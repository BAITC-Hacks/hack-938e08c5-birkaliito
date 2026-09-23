import pandas as pd
import pytest

from wind_forecast.data import read_config
from wind_forecast.weather import VARIABLES


@pytest.fixture
def config():
    return read_config()


@pytest.fixture
def weather(config):
    times = pd.date_range("2026-01-28", "2026-03-02", freq="h", tz="UTC")
    frames = []
    for turbine in (1, 2):
        for day in (2, 3):
            frame = pd.DataFrame({"valid_time": times, "turbine_id": turbine, "forecast_offset_days": day})
            for column in VARIABLES:
                frame[column] = 7.0
            frame["temperature_2m"] = 10.0
            frame["surface_pressure"] = 900.0
            frame["wind_direction_100m"] = 90.0
            frame["source_reference_time_upper_bound"] = frame.valid_time - pd.Timedelta(days=day)
            frame["available_at_upper_bound"] = frame.source_reference_time_upper_bound + pd.Timedelta(hours=6)
            frame["weather_model"] = config["weather_model"]
            frames.append(frame)
    return pd.concat(frames, ignore_index=True)
