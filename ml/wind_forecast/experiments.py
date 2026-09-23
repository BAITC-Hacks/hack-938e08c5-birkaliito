"""Supervised model search on calendar folds, with an honest regression check.

January has already been inspected in v1 and is labelled a regression check,
not a new blind test. Hyperparameters are selected without January labels.
"""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

from .features import as_utc, make_features, training_table
from .history import combine_features, history_features
from .model import estimator, interval_offsets, plot_backtest, predict_details, scores
from .validation import chronological_fold
from .weather import validate_weather

DEFAULT_FOLDS = ("2025-01-01", "2025-05-01", "2025-09-01", "2025-11-01")


def candidates(limit=10):
    result = [{"name": "v1_parameters", "max_depth": 7, "min_child_weight": 30,
               "reg_lambda": 15, "learning_rate": 0.035, "objective": "reg:squarederror", "fixed_trees": 99}]
    for depth in (3, 5, 7):
        for child, penalty in ((10, 5), (60, 30)):
            result.append({"name": f"squared_d{depth}_child{child}", "max_depth": depth,
                           "min_child_weight": child, "reg_lambda": penalty,
                           "learning_rate": 0.05, "objective": "reg:squarederror"})
    for depth in (3, 5, 7):
        result.append({"name": f"absolute_d{depth}", "max_depth": depth, "min_child_weight": 30,
                       "reg_lambda": 15, "learning_rate": 0.04, "objective": "reg:absoluteerror"})
    if not 1 <= limit <= len(result):
        raise ValueError(f"trials must be between 1 and {len(result)}")
    return result[:limit]


def build_estimator(candidate, trees=700, early_stopping=False):
    options = {key: value for key, value in candidate.items() if key not in ("name", "fixed_trees")}
    options.update(n_estimators=trees, reg_alpha=0.1, subsample=0.85, colsample_bytree=0.9,
                   tree_method="hist", n_jobs=4, random_state=42, eval_metric="mae")
    if early_stopping:
        options["early_stopping_rounds"] = 40
    return XGBRegressor(**options)


def fit_fold(candidate, features, target, fold, eligible):
    core = fold["core"] & eligible
    stopping = fold["stopping"] & eligible
    fit = fold["train"] & eligible
    if min(core.sum(), stopping.sum()) < 50:
        raise ValueError("Not enough eligible observations for supervised learning")
    curves = None
    trees = candidate.get("fixed_trees")
    if trees is None:
        learner = build_estimator(candidate, early_stopping=True)
        learner.fit(features[core], target[core],
                    eval_set=[(features[core], target[core]), (features[stopping], target[stopping])], verbose=False)
        trees = learner.best_iteration + 1
        curves = learner.evals_result()
    model = build_estimator(candidate, trees)
    model.fit(features[fit], target[fit])
    return model, int(trees), curves


def search(table, features, folds, configs, usable=None, fallback=None, label="weather"):
    eligible = pd.Series(True, index=table.index) if usable is None else usable
    runs = []
    for position, candidate in enumerate(configs, 1):
        rows, predictions, learning_curves = [], [], []
        for number, fold in enumerate(folds):
            model, trees, curves = fit_fold(candidate, features, table.power, fold, eligible)
            selected = fold["validation"]
            if fallback is None:
                prediction = np.clip(model.predict(features[selected]), 0, 1)
            else:
                prediction = fallback[number].copy()
                available = eligible[selected].to_numpy()
                if available.any():
                    prediction[available] = np.clip(model.predict(features[selected & eligible]), 0, 1)
            metrics = scores(table.loc[selected, "power"], prediction)
            rows.append({"start": str(fold["start"]), "end": str(fold["end"]),
                         "first_issue": str(fold["first_issue"]), "train_rows": int((fold["train"] & eligible).sum()),
                         "validation_rows": int(selected.sum()), "trees": trees, **metrics})
            predictions.append(prediction)
            learning_curves.append(curves)
        run = {"candidate": candidate, "folds": rows,
               "mean_mae": float(np.mean([row["mae"] for row in rows])),
               "mean_rmse": float(np.mean([row["rmse"] for row in rows])),
               "predictions": predictions, "curves": learning_curves}
        runs.append(run)
        print(f"{label} {position}/{len(configs)} {candidate['name']}: CV MAE={run['mean_mae']:.5f}", flush=True)
    best = min(runs, key=lambda run: run["mean_mae"])
    return best, runs


def serializable_runs(runs):
    return [{key: value for key, value in run.items() if key not in ("predictions", "curves")} for run in runs]


def improve(hourly, weather, config, artifact_dir="artifacts/improved", report_dir="reports/improved",
            fold_starts=DEFAULT_FOLDS, trials=10, calibration_start="2025-12-01",
            test_start="2026-01-01", test_end="2026-02-01"):
    validate_weather(weather, config)
    zone = config["timezone"]
    cal_start, check_start, check_end = [as_utc(value, zone) for value in (calibration_start, test_start, test_end)]
    starts = sorted(pd.Timestamp(value) for value in fold_starts)
    ends = [value + pd.DateOffset(months=1) for value in starts]
    if not starts or any(ends[i] > starts[i + 1] for i in range(len(starts) - 1)):
        raise ValueError("Validation months must be nonempty and nonoverlapping")
    if not as_utc(ends[-1], zone) <= cal_start < check_start < check_end:
        raise ValueError("Require CV end <= calibration start < test start < test end")
    table = training_table(hourly, weather, zone)
    table = table[table.valid_time < check_end].reset_index(drop=True)
    base = make_features(table, zone)
    history = history_features(hourly, table, config.get("history"))
    extended = combine_features(base, table, history)
    folds = [chronological_fold(table, start, end, zone) for start, end in zip(starts, ends)]
    configurations = candidates(trials)
    print(f"Supervised examples: {len(table)}; fresh history: {history.history_usable.mean():.1%}; folds: {len(folds)}", flush=True)
    best_weather, weather_runs = search(table, base, folds, configurations)
    best_history, history_runs = search(table, extended, folds, configurations, history.history_usable,
                                        best_weather["predictions"], label="weather+history")
    use_history = best_history["mean_mae"] < best_weather["mean_mae"]
    weather_trees = int(np.median([fold["trees"] for fold in best_weather["folds"]]))
    history_trees = int(np.median([fold["trees"] for fold in best_history["folds"]]))
    completed = table.valid_time + pd.Timedelta(hours=1)
    test_mask = table.valid_time.between(check_start, check_end, inclusive="left")
    if not test_mask.any():
        raise ValueError("No actual power measurements in requested regression period")
    first_test_issue = table.loc[test_mask, "issued_at"].min()
    calibration = table.valid_time.between(cal_start, check_start, inclusive="left") & (table.issued_at >= cal_start) & (completed <= first_test_issue)
    fitting = completed <= cal_start
    if calibration.sum() < 100 or (fitting & history.history_usable).sum() < 100:
        raise ValueError("Insufficient calibration/training rows")
    weather_model = build_estimator(best_weather["candidate"], weather_trees)
    weather_model.fit(base[fitting], table.loc[fitting, "power"])
    history_model = build_estimator(best_history["candidate"], history_trees)
    fresh_fit = fitting & history.history_usable
    history_model.fit(extended[fresh_fit], table.loc[fresh_fit, "power"])
    cal_weather = np.clip(weather_model.predict(base[calibration]), 0, 1)
    offsets = interval_offsets(table[calibration], cal_weather)
    fresh_cal = calibration & history.history_usable
    history_offsets = {**offsets, **interval_offsets(table[fresh_cal], np.clip(history_model.predict(extended[fresh_cal]), 0, 1))}
    bundle = {"schema_version": 2, "model": weather_model, "history_model": history_model,
              "use_history": use_history, "features": list(base), "history_features": list(extended), "config": config,
              "interval_offsets": offsets, "history_interval_offsets": history_offsets,
              "training_max_valid_time": str(table.loc[fitting, "valid_time"].max()),
              "calibration_max_valid_time": str(table.loc[calibration, "valid_time"].max()),
              "selected_parameters": {"weather": best_weather["candidate"], "history": best_history["candidate"],
                                      "weather_trees": weather_trees, "history_trees": history_trees}}
    test = table[test_mask].copy()
    weather_details = predict_details({**bundle, "use_history": False}, test, hourly)
    hybrid_details = predict_details({**bundle, "use_history": True}, test, hourly)
    selected_details = hybrid_details if use_history else weather_details
    for column in selected_details:
        test[column] = selected_details[column]
    baseline_model = estimator(7, 99)
    baseline_model.fit(base[fitting], table.loc[fitting, "power"])
    test["v1_prediction"] = np.clip(baseline_model.predict(base[test_mask]), 0, 1)
    test["weather_prediction"] = weather_details.prediction
    test["history_prediction"] = hybrid_details.prediction
    regression = {name: scores(test.power, test[column]) for name, column in
                  (("v1", "v1_prediction"), ("weather", "weather_prediction"), ("history_with_fallback", "history_prediction"), ("selected", "prediction"))}
    regression["selected"]["interval_80_coverage"] = float(test.power.between(test.lower_80, test.upper_80).mean())
    regression["selected"]["history_fraction"] = float((test.prediction_mode == "weather_and_history").mean())
    grouped = []
    for (turbine, day), group in test.groupby(["turbine_id", "forecast_offset_days"]):
        grouped.append({"turbine_id": int(turbine), "forecast_day": int(day - 1),
                        "v1": scores(group.power, group.v1_prediction), "selected": scores(group.power, group.prediction)})
    artifacts, reports = Path(artifact_dir), Path(report_dir)
    artifacts.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, artifacts / "evaluation_model.joblib")
    test.to_csv(artifacts / "regression_predictions.csv", index=False)
    production_issue = check_end - pd.Timedelta(hours=1)
    production = completed <= production_issue
    production_weather = build_estimator(best_weather["candidate"], weather_trees)
    production_weather.fit(base[production], table.loc[production, "power"])
    production_history = build_estimator(best_history["candidate"], history_trees)
    fresh_production = production & history.history_usable
    production_history.fit(extended[fresh_production], table.loc[fresh_production, "power"])
    production_bundle = {**bundle, "model": production_weather, "history_model": production_history,
                         "training_max_valid_time": str(table.loc[production, "valid_time"].max())}
    joblib.dump(production_bundle, artifacts / "model.joblib")
    joblib.dump({**production_bundle, "use_history": False}, artifacts / "weather_model.joblib")
    joblib.dump({**production_bundle, "use_history": True}, artifacts / "history_model.joblib")
    cv_predictions = []
    for number, fold in enumerate(folds):
        rows = table.loc[fold["validation"], ["issued_at", "valid_time", "turbine_id", "forecast_offset_days", "power"]].copy()
        rows["fold"] = str(fold["start"])
        rows["v1_prediction"] = weather_runs[0]["predictions"][number]
        rows["weather_prediction"] = best_weather["predictions"][number]
        rows["history_prediction"] = best_history["predictions"][number]
        cv_predictions.append(rows)
    pd.concat(cv_predictions).to_csv(artifacts / "cv_predictions.csv", index=False)
    selected_cv = best_history if use_history else best_weather
    baseline_cv = weather_runs[0]["mean_mae"]
    report = {"timezone": zone, "timezone_confirmed": config.get("timezone_confirmed", False),
              "learning": "supervised regression: archived weather and past SCADA -> actual hourly power",
              "selection": "lowest equally weighted monthly CV MAE; early stopping uses an inner past block",
              "validation_months": list(map(str, starts)), "weather_search": serializable_runs(weather_runs),
              "history_search": serializable_runs(history_runs),
              "cv": {"v1_mae": baseline_cv, "weather_mae": best_weather["mean_mae"],
                     "history_mae": best_history["mean_mae"], "selected_mae": selected_cv["mean_mae"],
                     "selected_gain_percent": (baseline_cv - selected_cv["mean_mae"]) / baseline_cv * 100},
              "selected_mode": "weather_and_history_with_fallback" if use_history else "weather_only",
              "parameters": bundle["selected_parameters"], "history_policy": config.get("history"),
              "regression_period": {"start": str(check_start), "end_exclusive": str(check_end)},
              "regression_is_new_blind_test": False, "regression": regression, "by_turbine_and_horizon": grouped,
              "training_max_valid_time": bundle["training_max_valid_time"],
              "calibration_max_valid_time": bundle["calibration_max_valid_time"],
              "production_training_max_valid_time": production_bundle["training_max_valid_time"],
              "limitations": ["January was already inspected in v1; this is a regression check, not a new blind test.",
                              "CV months are used to select parameters; report their scores as validation, not an independent test.",
                              "No SCADA after January supplied: February mostly uses the weather-only fallback.",
                              "Historical SCADA features assume measurements arrive at the end of their hour.",
                              "Empirical December interval coverage is not guaranteed after model refit."]}
    (reports / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    plot_backtest(test, reports / "regression.png", zone)
    save_learning_curve(selected_cv, reports)
    write_experiment_report(report, reports / "comparison.md")
    return refine_blend(hourly, weather, artifacts, reports)


def select_history_weight(predictions):
    """Choose a coarse blend using validation folds only, never regression labels."""
    trials = []
    for weight in (0.0, 0.25, 0.5, 0.75, 1.0):
        folds = []
        for month, group in predictions.groupby("fold"):
            values = (1 - weight) * group.weather_prediction + weight * group.history_prediction
            folds.append({"fold": str(month), **scores(group.power, values)})
        if not folds:
            raise ValueError("No validation folds for blend selection")
        trials.append({"history_weight": weight, "mean_mae": float(np.mean([row["mae"] for row in folds])),
                       "mean_rmse": float(np.mean([row["rmse"] for row in folds])), "folds": folds})
    return min(trials, key=lambda row: row["mean_mae"]), trials


def refine_blend(hourly, weather, artifact_dir="artifacts/improved", report_dir="reports/improved"):
    """Reuse fitted components; select their weight on CV and recalibrate bands."""
    artifacts, reports = Path(artifact_dir), Path(report_dir)
    report = json.loads((reports / "metrics.json").read_text(encoding="utf-8"))
    cv_predictions = pd.read_csv(artifacts / "cv_predictions.csv")
    best, blend_trials = select_history_weight(cv_predictions)
    weight = best["history_weight"]
    bundle = joblib.load(artifacts / "evaluation_model.joblib")
    bundle.update(use_history=weight > 0, history_weight=weight)
    config, zone = bundle["config"], bundle["config"]["timezone"]
    table = training_table(hourly, weather, zone)
    # Label boundaries remain identical to the original calibration step.
    cal_mask = ((table.issued_at >= as_utc(bundle["training_max_valid_time"], zone) + pd.Timedelta(hours=1))
                & (table.valid_time <= as_utc(bundle["calibration_max_valid_time"], zone)))
    calibration = table[cal_mask].copy()
    cal_details = predict_details(bundle, calibration, hourly)
    used = cal_details.prediction_mode.eq("weather_and_history")
    if used.any():
        bundle["history_interval_offsets"] = {**bundle["interval_offsets"],
            **interval_offsets(calibration[used], cal_details.loc[used, "prediction"].to_numpy())}
    test = pd.read_csv(artifacts / "regression_predictions.csv")
    for column in ("issued_at", "valid_time", "source_reference_time_upper_bound", "available_at_upper_bound"):
        test[column] = pd.to_datetime(test[column], utc=True)
    details = predict_details(bundle, test, hourly)
    for column in details:
        test[column] = details[column]
    test.to_csv(artifacts / "regression_predictions.csv", index=False)
    bundle["selected_parameters"]["history_weight"] = weight
    joblib.dump(bundle, artifacts / "evaluation_model.joblib")
    production = joblib.load(artifacts / "model.joblib")
    production.update(use_history=weight > 0, history_weight=weight,
                      history_interval_offsets=bundle["history_interval_offsets"], selected_parameters=bundle["selected_parameters"])
    joblib.dump(production, artifacts / "model.joblib")
    report["blend_search"] = blend_trials
    report["cv"]["selected_mae"] = best["mean_mae"]
    report["cv"]["selected_rmse"] = best["mean_rmse"]
    report["cv"]["selected_gain_percent"] = (report["cv"]["v1_mae"] - best["mean_mae"]) / report["cv"]["v1_mae"] * 100
    report["selected_mode"] = "weather_and_history_blend_with_fallback" if weight > 0 else "weather_only"
    report["parameters"] = bundle["selected_parameters"]
    report["regression"]["selected"] = {**scores(test.power, test.prediction),
        "interval_80_coverage": float(test.power.between(test.lower_80, test.upper_80).mean()),
        "history_fraction": float((test.prediction_mode == "weather_and_history").mean())}
    for item in report["by_turbine_and_horizon"]:
        group = test[(test.turbine_id == item["turbine_id"]) & (test.forecast_offset_days == item["forecast_day"] + 1)]
        item["selected"] = scores(group.power, group.prediction)
    (reports / "metrics.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    plot_backtest(test, reports / "regression.png", zone)
    write_experiment_report(report, reports / "comparison.md")
    print(json.dumps({"cv": report["cv"], "history_weight": weight, "regression": report["regression"]}, indent=2), flush=True)
    return production, report


def save_learning_curve(selected, output):
    curves = next((value for value in reversed(selected["curves"]) if value), None)
    if not curves:
        return
    frame = pd.DataFrame({"training_mae": curves["validation_0"]["mae"], "early_stopping_mae": curves["validation_1"]["mae"]})
    frame.index.name = "boosting_iteration"
    frame.to_csv(output / "learning_curve.csv")
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ax = frame.plot(figsize=(9, 4), title="Supervised learning: error vs boosting iteration", ylabel="MAE")
    ax.figure.tight_layout()
    ax.figure.savefig(output / "learning_curve.png", dpi=150)
    plt.close(ax.figure)


def write_experiment_report(report, path):
    cv = report["cv"]
    lines = ["# Сравнение моделей с обучением с учителем", "",
             "Входы: архивные прогнозы погоды и, при наличии, завершённые прошлые измерения. Ответ: фактическая почасовая мощность.", "",
             f"Часовой пояс: `{report['timezone']}`; подтверждён пользователем: {report['timezone_confirmed']}.", "",
             "Параметры выбираются по четырём временным блокам (при стандартных настройках), ранняя остановка — по отдельному прошлому блоку внутри обучения.", "",
             "| Вариант | Средняя MAE на временной валидации |", "|---|---:|",
             f"| Прежние параметры | {cv['v1_mae']:.5f} |", f"| Подбор, только погода | {cv['weather_mae']:.5f} |",
             f"| Подбор, погода + история с резервным режимом | {cv['history_mae']:.5f} |",
             f"| Выбранная комбинация | {cv['selected_mae']:.5f} |", "",
             f"Выбран режим `{report['selected_mode']}`. Изменение MAE относительно прежних параметров: {cv['selected_gain_percent']:.2f}% улучшения.", "",
             f"Вес модели с историей: {report['parameters'].get('history_weight', 1.0 if 'history' in report['selected_mode'] else 0.0):.0%}. Проверены веса 0/25/50/75/100% только по временной валидации.", "",
             "## Проверка на ранее просмотренном январе", "",
             "Этот период уже использовался в первом отчёте. Он не является новым слепым тестом; параметры текущего поиска выбирались без январских целей.", "",
             "| Вариант | MAE | RMSE | R² |", "|---|---:|---:|---:|"]
    for name, values in report["regression"].items():
        lines.append(f"| {name} | {values['mae']:.5f} | {values['rmse']:.5f} | {values['r2']:.4f} |")
    lines += ["", "![Проверка прогноза](regression.png)", "",
              "В феврале новых измерений SCADA нет: при устаревании истории используется погодная модель. Будущая фактическая мощность в признаки не попадает.", "",
              "Для независимой оценки улучшения нужны ещё не использованные фактические измерения, например за февраль."]
    if (path.parent / "learning_curve.png").exists():
        lines += ["", "## Как модель учится", "", "На каждой итерации новые деревья корректируют ошибки относительно известных ответов. График показывает ошибку на обучающих примерах и отдельном блоке ранней остановки.", "", "![Кривая обучения](learning_curve.png)"]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
