import numpy as np
import pandas as pd
import pytest

from wind_forecast.data import load_turbine


def write_scada(path, times, power=None):
    pd.DataFrame({"timestamp": times, "wind_speed": 6.0, "power": 0.4 if power is None else power, "temperature": 12.0}).to_csv(path, index=False)


def test_missing_hours_are_not_filled_or_compressed(tmp_path):
    times = pd.date_range("2025-01-01", periods=6, freq="10min").append(pd.date_range("2025-01-01 02:00", periods=5, freq="10min"))
    path = tmp_path / "turbine.csv"
    write_scada(path, times)
    hourly, profile = load_turbine(path, 1, "UTC")
    assert len(hourly) == 3
    assert hourly.power.iloc[0] == pytest.approx(0.4)
    assert hourly.power.iloc[1:].isna().all()
    assert profile["missing_or_incomplete_hours"] == 2


def test_duplicates_rejected(tmp_path):
    path = tmp_path / "turbine.csv"
    write_scada(path, ["2025-01-01", "2025-01-01"])
    with pytest.raises(ValueError, match="Duplicate"):
        load_turbine(path, 1, "UTC")


def test_out_of_range_and_infinite_values_cannot_be_targets(tmp_path):
    path = tmp_path / "turbine.csv"
    write_scada(path, pd.date_range("2025-01-01", periods=6, freq="10min"), [0.5, 0.6, -1, 1.2, np.inf, 0.7])
    hourly, profile = load_turbine(path, 1, "UTC")
    assert profile["invalid_rows"] == 3
    assert hourly.power.isna().all()


def test_almaty_ambiguous_hour_is_explicitly_excluded(tmp_path):
    path = tmp_path / "turbine.csv"
    write_scada(path, pd.date_range("2024-02-29 22:00", periods=18, freq="10min"))
    _, profile = load_turbine(path, 1, "Asia/Almaty")
    assert profile["ambiguous_or_nonexistent_time_rows"] == 6
