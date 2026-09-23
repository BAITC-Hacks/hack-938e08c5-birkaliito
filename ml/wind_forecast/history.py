"""Issue-time SCADA snapshots. Targets from unfinished/future hours are excluded."""

import numpy as np
import pandas as pd

HISTORY_VARIABLES = ("power", "wind_speed", "temperature")


def history_features(hourly, frame, policy=None):
    """Return trailing features aligned to each issue, never to the target time.

    A SCADA row labelled 22:00 describes [22:00, 23:00), so it becomes usable
    at 23:00. Calendar-hour reindexing preserves gaps before rolling/lagging.
    """
    policy = policy or {}
    max_age = float(policy.get("max_age_hours", 3))
    min_count = int(policy.get("min_samples_24h", 12))
    if max_age < 0 or not 1 <= min_count <= 24:
        raise ValueError("Invalid history freshness/coverage policy")
    columns = ["history_age_hours", "history_count_24h"]
    for variable in HISTORY_VARIABLES:
        columns += [f"observed_{variable}_last"]
        columns += [f"observed_{variable}_lag_{lag}h" for lag in (3, 6, 24)]
        columns += [f"observed_{variable}_mean_{window}h" for window in (3, 6, 24, 72)]
        columns += [f"observed_{variable}_std_24h"]
    result = pd.DataFrame(np.nan, index=frame.index, columns=columns)
    result["history_usable"] = False
    if hourly is None or hourly.empty:
        return result
    required = {"valid_time", "turbine_id", *HISTORY_VARIABLES}
    if required - set(hourly):
        raise ValueError(f"History lacks columns: {sorted(required - set(hourly))}")
    if hourly.duplicated(["valid_time", "turbine_id"]).any():
        raise ValueError("Duplicate hourly history observations")
    # Discard data newer than the latest issue even before computing snapshots.
    available = hourly[hourly.valid_time + pd.Timedelta(hours=1) <= frame.issued_at.max()]
    for turbine, targets in frame.groupby("turbine_id"):
        history = available[available.turbine_id == turbine].set_index("valid_time").sort_index()
        if history.empty:
            continue
        history = history.reindex(pd.date_range(history.index.min(), history.index.max(), freq="h"))
        snapshots = pd.DataFrame(index=history.index)
        complete = history[list(HISTORY_VARIABLES)].notna().all(axis=1)
        snapshots["history_count_24h"] = complete.rolling(24, min_periods=1).sum()
        for variable in HISTORY_VARIABLES:
            series = history[variable].where(complete)
            snapshots[f"observed_{variable}_last"] = series
            for lag in (3, 6, 24):
                snapshots[f"observed_{variable}_lag_{lag}h"] = series.shift(lag)
            for window in (3, 6, 24, 72):
                snapshots[f"observed_{variable}_mean_{window}h"] = series.rolling(window, min_periods=max(1, window // 2)).mean()
            snapshots[f"observed_{variable}_std_24h"] = series.rolling(24, min_periods=12).std()
        snapshots["available_at"] = snapshots.index + pd.Timedelta(hours=1)
        snapshots = snapshots.loc[complete].reset_index(drop=True)
        if snapshots.empty:
            continue
        wanted = targets[["issued_at"]].assign(row_id=np.arange(len(targets)))
        joined = pd.merge_asof(wanted.sort_values("issued_at"), snapshots, left_on="issued_at", right_on="available_at", direction="backward")
        joined = joined.sort_values("row_id")
        joined["history_age_hours"] = (joined.issued_at - joined.available_at).dt.total_seconds() / 3600
        fresh = joined.history_age_hours.between(0, max_age) & (joined.history_count_24h >= min_count)
        result.loc[targets.index, columns] = joined[columns].to_numpy()
        result.loc[targets.index, "history_usable"] = fresh.to_numpy()
    return result


def combine_features(base, frame, history):
    extra = history.drop(columns="history_usable")
    result = pd.concat([base, extra], axis=1)
    result["horizon_hours"] = frame.horizon_hours.astype(float)
    result["wind_change_from_observed"] = frame.wind_speed_100m - history.observed_wind_speed_last
    result["temperature_change_from_observed"] = frame.temperature_2m - history.observed_temperature_last
    result["recent_power_trend"] = history.observed_power_last - history.observed_power_mean_6h
    return result
