"""Score frozen predictions against observed hourly targets without fitting."""

import json
from pathlib import Path

import numpy as np
import pandas as pd

from .model import scores


def evaluate(predictions, hourly, output_dir="outputs/evaluation"):
    predictions = predictions.copy()
    required = {"issued_at", "valid_time", "turbine_id", "prediction"}
    if required - set(predictions) or predictions.empty:
        raise ValueError("Expected nonempty forecasts with issued_at, valid_time, turbine_id, prediction")
    for column in ("issued_at", "valid_time"):
        predictions[column] = pd.to_datetime(predictions[column], utc=True, errors="raise")
    if predictions[["issued_at", "valid_time", "turbine_id"]].isna().any().any():
        raise ValueError("Missing forecast keys")
    if predictions.duplicated(["issued_at", "valid_time", "turbine_id"]).any():
        raise ValueError("Duplicate prediction keys")
    if not (predictions.valid_time > predictions.issued_at).all():
        raise ValueError("Predictions must be issued before their target hour")
    if not predictions.prediction.between(0, 1).all():
        raise ValueError("Predictions must be finite and between 0 and 1")
    observed = hourly[["valid_time", "turbine_id", "power"]].rename(columns={"power": "actual_power"})
    observed["valid_time"] = pd.to_datetime(observed.valid_time, utc=True, errors="raise")
    joined = predictions.merge(observed, on=["valid_time", "turbine_id"], how="left", validate="many_to_one")
    valid = joined.actual_power.between(0, 1) & np.isfinite(joined.actual_power)
    matched = joined[valid].copy()
    if matched.empty:
        raise ValueError("No complete actual hourly measurements match these predictions")
    matched["error"] = matched.prediction - matched.actual_power
    matched["absolute_error"] = matched.error.abs()
    matched["forecast_day"] = np.ceil((matched.valid_time - matched.issued_at).dt.total_seconds() / 86400).astype(int)
    groups = [{"turbine_id": int(turbine), "forecast_day": int(day), "rows": len(group),
               **scores(group.actual_power, group.prediction)}
              for (turbine, day), group in matched.groupby(["turbine_id", "forecast_day"])]
    report = {"forecast_rows": len(predictions), "scored_rows": len(matched),
              "missing_or_invalid_actual_rows": int((~valid).sum()), "target_coverage": float(valid.mean()),
              "metrics": scores(matched.actual_power, matched.prediction),
              "mean_signed_error": float(matched.error.mean()), "by_turbine_and_horizon": groups,
              "note": "Scoring only. No training or model selection; a new independent test also requires previously unseen targets."}
    if {"lower_80", "upper_80"} <= set(matched):
        bounds = matched[["lower_80", "upper_80"]]
        if bounds.isna().any().any() or not np.isfinite(bounds).all().all() or (bounds.lower_80 > bounds.upper_80).any():
            raise ValueError("Invalid prediction interval bounds")
        report["interval_80_coverage"] = float(matched.actual_power.between(matched.lower_80, matched.upper_80).mean())
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    matched.to_csv(output / "predictions_vs_actual.csv", index=False)
    (output / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report
