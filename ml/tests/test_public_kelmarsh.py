import numpy as np
import pandas as pd
import pytest

from scripts.public_kelmarsh import prepare_hourly


def sparse_export():
    stamps = pd.date_range("2024-01-01", periods=17, freq="10min")
    power = pd.DataFrame({"# Date and time": stamps, "Power (kW)": [1000] * 6 + [-2] * 6 + [1200] * 5,
                          "Wind speed (m/s)": np.nan, "Nacelle ambient temperature (C)": np.nan})
    weather = power.assign(**{"Power (kW)": np.nan, "Wind speed (m/s)": 8.0,
                              "Nacelle ambient temperature (C)": 15.0})
    return pd.concat([power, weather], ignore_index=True)


def test_sparse_duplicates_coalesce_without_inflating_hourly_sample_count():
    hourly, quality = prepare_hourly(sparse_export(), rated_kw=2000)
    assert quality["duplicate_timestamp_rows"] == 17
    assert quality["complete_power_hours"] == 2
    assert hourly.samples.tolist() == [6, 6, 5]
    assert hourly.loc[0, "power"] == 0.5
    assert hourly.loc[0, "wind_speed"] == 8
    assert hourly.loc[0, "temperature"] == 15
    assert hourly.loc[1, "power"] == 0
    assert hourly.loc[1, "power_raw_normalized"] == -0.001
    assert pd.isna(hourly.loc[2, "power"])
    assert str(hourly.valid_time.dt.tz) == "UTC"


def test_conflicting_duplicate_measurements_are_rejected():
    source = sparse_export()
    conflict = source.iloc[[0]].assign(**{"Power (kW)": 999})
    with pytest.raises(ValueError, match="Conflicting duplicate"):
        prepare_hourly(pd.concat([source, conflict], ignore_index=True), rated_kw=2000)


def test_off_grid_timestamp_is_rejected():
    source = sparse_export()
    source.loc[0, "# Date and time"] += pd.Timedelta(minutes=1)
    with pytest.raises(ValueError, match="ten-minute UTC"):
        prepare_hourly(source, rated_kw=2000)
