"""Temporal model selection, untouched January test, and production refit."""

import json
import platform
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import sklearn
import xgboost
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from xgboost import XGBRegressor

from .features import as_utc, make_features, training_table
from .weather import validate_weather


def scores(actual, predicted):
    return {"mae": float(mean_absolute_error(actual, predicted)),
            "rmse": float(np.sqrt(mean_squared_error(actual, predicted))),
            "r2": float(r2_score(actual, predicted))}


def estimator(depth, trees=600):
    return XGBRegressor(
        n_estimators=trees, max_depth=depth, learning_rate=0.035,
        min_child_weight=30, subsample=0.85, colsample_bytree=0.9,
        reg_lambda=15, reg_alpha=0.1, objective="reg:squarederror",
        tree_method="hist", n_jobs=4, random_state=42,
    )


def interval_offsets(frame, predictions):
    residuals = frame.assign(residual=frame.power.to_numpy() - predictions)
    result = {}
    for (turbine, day), group in residuals.groupby(["turbine_id", "forecast_offset_days"]):
        lo, hi = np.quantile(group.residual, [0.1, 0.9])
        result[f"{int(turbine)}:{int(day)}"] = [float(min(lo, 0)), float(max(hi, 0))]
    return result


def predict_details(bundle, frame, hourly=None):
    features = make_features(frame, bundle["config"]["timezone"])
    if list(features.columns) != bundle["features"]:
        raise ValueError("Feature schema does not match the trained model")
    predictions = np.clip(bundle["model"].predict(features), 0, 1)
    used_history = np.zeros(len(frame), dtype=bool)
    ages = np.full(len(frame), np.nan)
    if bundle.get("history_model") is not None and bundle.get("use_history", True):
        from .history import combine_features, history_features
        history = history_features(hourly, frame, bundle["config"].get("history"))
        extended = combine_features(features, frame, history)
        if list(extended.columns) != bundle["history_features"]:
            raise ValueError("History feature schema does not match trained model")
        used_history = history.history_usable.to_numpy()
        ages = history.history_age_hours.to_numpy()
        if used_history.any():
            weight = float(bundle.get("history_weight", 1.0))
            if not 0 <= weight <= 1:
                raise ValueError("History blend weight must be between 0 and 1")
            history_prediction = np.clip(bundle["history_model"].predict(extended.loc[used_history]), 0, 1)
            predictions[used_history] = (1 - weight) * predictions[used_history] + weight * history_prediction
    offsets = np.array([bundle["interval_offsets"][f"{int(t)}:{int(d)}"] for t, d in zip(frame.turbine_id, frame.forecast_offset_days)])
    if used_history.any():
        history_offsets = bundle.get("history_interval_offsets", bundle["interval_offsets"])
        offsets[used_history] = [history_offsets[f"{int(t)}:{int(d)}"] for t, d in zip(frame.loc[used_history, "turbine_id"], frame.loc[used_history, "forecast_offset_days"])]
    return pd.DataFrame({"prediction": predictions,
                         "lower_80": np.clip(predictions + offsets[:, 0], 0, 1),
                         "upper_80": np.clip(predictions + offsets[:, 1], 0, 1),
                         "prediction_mode": np.where(used_history, "weather_and_history", "weather_only"),
                         "history_age_hours": ages}, index=frame.index)


def predict_bundle(bundle, frame, hourly=None):
    details = predict_details(bundle, frame, hourly)
    return tuple(details[column].to_numpy() for column in ("prediction", "lower_80", "upper_80"))


def persistence_predictions(hourly, targets):
    result = pd.Series(np.nan, index=targets.index, dtype=float)
    for turbine, group in targets.groupby("turbine_id"):
        history = hourly[(hourly.turbine_id == turbine) & hourly.power.notna()].sort_values("valid_time")
        known = history.assign(available_at=history.valid_time + pd.Timedelta(hours=1))[["available_at", "power"]]
        wanted = group[["issued_at"]].copy()
        wanted["row_index"] = group.index
        joined = pd.merge_asof(wanted.sort_values("issued_at"), known, left_on="issued_at", right_on="available_at", direction="backward", tolerance=pd.Timedelta(hours=24))
        result.loc[joined.row_index] = joined.power.to_numpy()
    return result.to_numpy()


def train(hourly, weather, config, artifact_dir="artifacts", report_dir="reports"):
    validate_weather(weather, config)
    table = training_table(hourly, weather, config["timezone"])
    boundaries = {name: as_utc(date, config["timezone"]) for name, date in {
        "validation": "2025-11-01", "calibration": "2025-12-01", "test": "2026-01-01", "end": "2026-02-01"
    }.items()}
    table = table[table.valid_time < boundaries["end"]].reset_index(drop=True)
    masks = {
        "train": table.valid_time < boundaries["validation"],
        "validation": table.valid_time.between(boundaries["validation"], boundaries["calibration"], inclusive="left") & (table.issued_at >= boundaries["validation"]),
        "calibration": table.valid_time.between(boundaries["calibration"], boundaries["test"], inclusive="left") & (table.issued_at >= boundaries["calibration"]),
        "test": table.valid_time >= boundaries["test"],
    }
    first_test_origin = table.loc[masks["test"], "issued_at"].min()
    masks["calibration"] &= table.valid_time + pd.Timedelta(hours=1) <= first_test_origin
    if any(mask.sum() < 100 for mask in masks.values()):
        raise ValueError("Not enough data in chronological train/validation/calibration/test blocks")
    features, target = make_features(table, config["timezone"]), table.power
    experiments = []
    for depth in (3, 5, 7):
        candidate = estimator(depth)
        candidate.set_params(early_stopping_rounds=40)
        candidate.fit(features[masks["train"]], target[masks["train"]], eval_set=[(features[masks["validation"]], target[masks["validation"]])], verbose=False)
        metrics = scores(target[masks["validation"]], np.clip(candidate.predict(features[masks["validation"]]), 0, 1))
        trial = {"depth": depth, "trees": candidate.best_iteration + 1, **metrics}
        experiments.append(trial)
        print(f"Validation: {trial}", flush=True)
    best = min(experiments, key=lambda item: item["mae"])
    fit_mask = table.valid_time < boundaries["calibration"]
    evaluation_model = estimator(best["depth"], best["trees"])
    evaluation_model.fit(features[fit_mask], target[fit_mask])
    calibration_predictions = np.clip(evaluation_model.predict(features[masks["calibration"]]), 0, 1)
    offsets = interval_offsets(table[masks["calibration"]], calibration_predictions)
    bundle = {"model": evaluation_model, "config": config, "features": list(features), "interval_offsets": offsets,
              "training_max_valid_time": str(table.loc[fit_mask, "valid_time"].max()),
              "calibration_max_valid_time": str(table.loc[masks["calibration"], "valid_time"].max()),
              "schema_version": 1, "selected_parameters": best}
    test = table[masks["test"]].copy()
    test["prediction"], test["lower_80"], test["upper_80"] = predict_bundle(bundle, test)
    means = table[fit_mask].groupby("turbine_id").power.mean()
    test["baseline_mean"] = test.turbine_id.map(means)
    test["baseline_persistence"] = persistence_predictions(hourly, test)
    monthly = table[fit_mask].assign(month=table.loc[fit_mask, "valid_time"].dt.tz_convert(config["timezone"]).dt.month).groupby(["turbine_id", "month"]).power.mean()
    test["baseline_seasonal"] = [monthly.get((int(t), int(m)), means.loc[t]) for t, m in zip(test.turbine_id, test.valid_time.dt.tz_convert(config["timezone"]).dt.month)]
    metrics = scores(test.power, test.prediction)
    metrics["interval_80_coverage"] = float(test.power.between(test.lower_80, test.upper_80).mean())
    metrics["interval_80_mean_width"] = float((test.upper_80 - test.lower_80).mean())
    baseline_scores = {}
    for column in ["baseline_mean", "baseline_seasonal", "baseline_persistence"]:
        subset = test.dropna(subset=[column])
        baseline_scores[column] = {**scores(subset.power, subset[column]), "rows": len(subset)}
    grouped = []
    for (turbine, day), group in test.groupby(["turbine_id", "forecast_offset_days"]):
        grouped.append({"turbine_id": int(turbine), "forecast_day": int(day - 1), "rows": len(group), **scores(group.power, group.prediction)})
    report = {
        "timezone_assumption": config["timezone"], "timezone_confirmed": config.get("timezone_confirmed", False), "weather_model": config["weather_model"],
        "target": "hourly normalized active power (0..1)", "train_validation_cutoffs_utc": {k: str(v) for k, v in boundaries.items()},
        "rows": {k: int(v.sum()) for k, v in masks.items()}, "validation_experiments": experiments,
        "chosen_parameters": best, "january_2026_test": metrics, "baselines": baseline_scores,
        "by_turbine_and_horizon": grouped,
        "versions": {"python": platform.python_version(), "numpy": np.__version__, "pandas": pd.__version__, "sklearn": sklearn.__version__, "xgboost": xgboost.__version__},
        "limitations": [
            "No February targets supplied: February accuracy cannot be measured.",
            "Timestamp timezone: " + ("confirmed by user." if config.get("timezone_confirmed") else "an explicit assumption until confirmed by the data owner."),
            "Previous Runs has fixed-lead forecasts; exact operational run IDs are unavailable.",
            "Availability is a conservative bound with a 6h publication allowance, not an observed publication timestamp.",
            "Intervals are empirical December residual bands, not a coverage guarantee after production refit.",
            "Power is normalized. MWh requires turbine rated capacities and confirmation of normalization semantics.",
        ],
    }
    artifacts, reports = Path(artifact_dir), Path(report_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, artifacts / "evaluation_model.joblib")
    test.to_csv(artifacts / "january_backtest.csv", index=False)
    production_model = estimator(best["depth"], best["trees"])
    first_february_issue = boundaries["end"] - pd.Timedelta(hours=1)
    production_mask = table.valid_time + pd.Timedelta(hours=1) <= first_february_issue
    production_model.fit(features[production_mask], target[production_mask])
    production_bundle = {**bundle, "model": production_model, "training_max_valid_time": str(table.loc[production_mask, "valid_time"].max())}
    report["production_training_max_valid_time"] = production_bundle["training_max_valid_time"]
    report["calibration_max_valid_time"] = bundle["calibration_max_valid_time"]
    joblib.dump(production_bundle, artifacts / "model.joblib")
    (reports / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    importance = pd.DataFrame({"feature": features.columns, "importance": production_model.feature_importances_}).sort_values("importance", ascending=False)
    importance.to_csv(reports / "feature_importance.csv", index=False)
    plot_backtest(test, reports / "january_backtest.png", config["timezone"])
    write_report(report, reports / "model_report.md")
    print(json.dumps(metrics, indent=2), flush=True)
    return production_bundle, report


def plot_backtest(test, path, timezone):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(2, 1, figsize=(14, 7), sharex=True)
    for ax, (turbine, group) in zip(axes, test[test.forecast_offset_days == 2].groupby("turbine_id")):
        group = group.sort_values("valid_time").head(24 * 7)
        dates = group.valid_time.dt.tz_convert(timezone)
        ax.plot(dates, group.power, label="Observed", linewidth=1.3)
        ax.plot(dates, group.prediction, label="24h forecast", linewidth=1.1)
        ax.fill_between(dates, group.lower_80, group.upper_80, alpha=0.15, label="Empirical 80% band")
        ax.set(title=f"Turbine {turbine}", ylabel="Normalized power", ylim=(0, 1.05))
        ax.legend(loc="upper right", ncol=3)
        ax.grid(alpha=0.2)
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def write_report(report, path):
    metrics = report["january_2026_test"]
    lines = ["# Отчёт о модели ВЭС", "", "Проверка: январь 2026, исключённый из обучения и подбора параметров.", "",
             f"Часовой пояс CSV: `{report['timezone_assumption']}` ({'подтверждён' if report.get('timezone_confirmed') else 'допущение'}). Источник: архивные прогнозы GFS.", "",
             f"MAE: **{metrics['mae']:.4f}**, RMSE: **{metrics['rmse']:.4f}**, R²: **{metrics['r2']:.4f}**.", "",
             "MAE измеряется в долях нормализованной мощности, а не в процентах от фактической выработки.", "",
             "| Модель | MAE | RMSE |", "|---|---:|---:|", f"| XGBoost | {metrics['mae']:.4f} | {metrics['rmse']:.4f} |"]
    for name, values in report["baselines"].items():
        lines.append(f"| {name} | {values['mae']:.4f} | {values['rmse']:.4f} |")
    lines += ["", "| Турбина | Горизонт | MAE | RMSE |", "|---|---|---:|---:|"]
    for row in report["by_turbine_and_horizon"]:
        lines.append(f"| {row['turbine_id']} | {'1–24 ч' if row['forecast_day'] == 1 else '25–48 ч'} | {row['mae']:.4f} | {row['rmse']:.4f} |")
    lines += ["", f"Покрытие эмпирического 80% интервала на январе: {metrics['interval_80_coverage']:.1%}.", "",
              "Финальная модель переобучена на всех доступных целях до 1 февраля; приведённые метрики относятся к отдельной проверочной модели.", "",
              "В феврале фактическая мощность не предоставлена: качество февральского прогноза пока неизвестно.", "",
              "![Проверка на январе](january_backtest.png)", "", "Все параметры, разбиения и ограничения: [metrics.json](metrics.json)."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
