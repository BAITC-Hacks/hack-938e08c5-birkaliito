"""Time-based folds with a label-availability embargo and inner early stopping."""

import pandas as pd

from .features import as_utc


def chronological_fold(table, start, end, timezone, early_stop_days=28):
    start, end = as_utc(start, timezone), as_utc(end, timezone)
    if start >= end or early_stop_days < 1:
        raise ValueError("Invalid validation boundaries")
    validation = table.valid_time.between(start, end, inclusive="left")
    if not validation.any():
        raise ValueError(f"No target observations in {start}..{end}")
    first_issue = table.loc[validation, "issued_at"].min()
    completed = table.valid_time + pd.Timedelta(hours=1)
    train = completed <= first_issue
    inner_cutoff = first_issue - pd.Timedelta(days=early_stop_days)
    core = completed <= inner_cutoff
    stopping = train & (table.issued_at >= inner_cutoff)
    if min(core.sum(), stopping.sum(), validation.sum()) < 50:
        raise ValueError("Insufficient data for chronological train/early-stop/validation blocks")
    return {"train": train, "core": core, "stopping": stopping, "validation": validation,
            "first_issue": first_issue, "start": start, "end": end, "inner_cutoff": inner_cutoff}
