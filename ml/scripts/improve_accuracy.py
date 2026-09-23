"""Select for +/-10 pp on 2025 calendar folds, then inspect January once.

Run from ml/: python scripts/improve_accuracy.py
No future measured weather is used as an input. No existing artifact is replaced.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import joblib
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from wind_forecast.accuracy import CENTERS, WindowRegressor, accuracy_scores
from wind_forecast.data import read_config, read_hourly
from wind_forecast.experiments import DEFAULT_FOLDS, build_estimator
from wind_forecast.features import as_utc, make_features, training_table
from wind_forecast.history import combine_features, history_features
from wind_forecast.model import interval_offsets, predict_details
from wind_forecast.validation import chronological_fold
from wind_forecast.weather import VARIABLES, read_weather, validate_weather

KEYS = ["issued_at", "valid_time", "turbine_id", "forecast_offset_days"]


def write_report(decision, regression, reports):
    baseline, current, selected = decision["baseline_january"], decision["january"], decision["selected"]
    severe = float(((regression.prediction - regression.power).abs() > .30).mean())
    decision["january_error_over_30pp"] = severe
    lines = ["# Улучшение доли попаданий в ±10 п.п.", "",
             f"Цель: **80%**. Получено на январе: **{current['hit_rate_10pp']:.2%}**; "
             f"на четырёх месяцах CV: **{selected['mean_hit_rate_10pp']:.2%}**.", "",
             "Цель достигнута в этих проверках." if decision["target_reached"] else "**80% не достигнуто.** Результат не подтверждает такой уровень на будущих данных.", "",
             "Попадание = `abs(прогноз − факт) <= 0.10` на исходной шкале мощности 0…1. "
             "Это ±10 процентных пунктов, а не относительная ошибка 10% и не R².", "",
             "| Январь 2026, те же часы | Прежняя модель | Выбранный вариант |",
             "|---|---:|---:|",
             f"| Попадания | {baseline['hit_rate_10pp']:.2%} | {current['hit_rate_10pp']:.2%} |",
             f"| Число попаданий | {baseline['hits_10pp']}/{baseline['rows']} | {current['hits_10pp']}/{current['rows']} |",
             f"| MAE, п.п. | {baseline['mae'] * 100:.2f} | {current['mae'] * 100:.2f} |",
             f"| RMSE, п.п. | {baseline['rmse'] * 100:.2f} | {current['rmse'] * 100:.2f} |",
             f"| R² | {baseline['r2']:.4f} | {current['r2']:.4f} |", "",
             f"Выбран `{selected['name']}`. Ошибка больше 30 п.п.: **{severe:.2%}** строк.", "",
             f"Для сравнения: постоянный прогноз {decision['constant_baseline']['prediction']:.2f}, "
             f"выбранный по обучающим данным, даёт **{decision['constant_baseline']['hit_rate_10pp']:.2%}** "
             f"попаданий на январе (MAE {decision['constant_baseline']['mae'] * 100:.2f} п.п.). "
             "Поэтому большой прирост относительно 32,1% сам по себе ещё не означает качественный прогноз всех режимов.", "",
             "## Что изменилось", "",
             "Сравниваются GFS и ICON, модели по погоде и модели с доступной на момент выпуска "
             "историей SCADA. Кроме регрессии по MAE проверяется модель вероятности попадания: "
             "17 перекрывающихся окон с центрами 0.10…0.90 и шагом 0.05. Для каждого окна "
             "XGBoost обучается оценивать вероятность попадания факта в ±0.10 от центра. "
             "Прогнозом становится центр с максимальной вероятностью. Это может повысить "
             "число попаданий ценой увеличения отдельных промахов; MAE и RMSE приведены выше.", "",
             "## Временной протокол", "",
             "- Отбор: январь, май, сентябрь и ноябрь 2025, равные веса месяцев. "
             "Внутренний прошлый блок используется для ранней остановки.",
             "- Обучение каждого блока использует лишь часы, завершившиеся до первого выпуска прогноза блока.",
             "- Итоговая проверочная модель обучена до 1 декабря 2025. Декабрь используется для интервалов; "
             "январские цели не используются для выбора модели или числа деревьев.",
             "- Январь 2026 уже изучался ранее: это повторная проверка, не новый слепой тест. "
             "2976 строк — 1488 часов турбин с двумя горизонтами; строки не независимы.",
             "- Фактический будущий ветер не входит в признаки. История — только завершённые прошлые часы. "
             "Горизонты 1–24 и 25–48 часов, выпуск 23:00 Asia/Almaty сохранены.",
             "- Пропуски дополнительной погоды не удаляют неудобные часы из оценки; XGBoost получает NaN. "
             "Обычный выпуск через forecast по-прежнему требует полного погодного входа.", "",
             "## Сравнение вариантов на CV", "",
             "| Вариант | Средняя доля попаданий | Средняя MAE, п.п. |", "|---|---:|---:|",
             f"| Прежняя комбинация | {decision['baseline_cv']['mean_hit_rate_10pp']:.2%} | {decision['baseline_cv']['mean_mae'] * 100:.2f} |"]
    for run in sorted(decision["runs"], key=lambda row: -row["mean_hit_rate_10pp"]):
        lines.append(f"| {run['name']} | {run['mean_hit_rate_10pp']:.2%} | {run['mean_mae'] * 100:.2f} |")
    lines += ["", "## Январь по турбине и горизонту", "", "| Турбина | Сутки прогноза | Попадания | MAE, п.п. |", "|---|---|---:|---:|"]
    for row in decision["by_turbine_and_day"]:
        lines.append(f"| {row['turbine']} | {row['day']} | {row['hit_rate_10pp']:.2%} | {row['mae'] * 100:.2f} |")
    lines += ["", "## Погода и следующий шаг", "",
              "Источники: [Open-Meteo Previous Runs](https://open-meteo.com/en/docs/previous-runs-api), "
              "модели `gfs_global` и `icon_global`. Использованы архивные прогнозы с фиксированным "
              "опережением 48/72 часа и запасом публикации 6 часов. Это консервативная оценка "
              "доступности, а не точные идентификаторы оперативных запусков. URL и время скачивания "
              "сохранены в локальных JSON-кэшах. Измерения турбин никуда не отправлялись.", "",
              "Для дальнейшей проверки нужны более точные прогнозы ветра для точки и высоты ротора "
              "с временем выпуска, подтверждённая высота датчика и новые измерения мощности после "
              "января 2026. Проверить более свежие запуски и локальную коррекцию ветра следует на "
              "этом новом периоде. Наличие этих данных само по себе не гарантирует 80%.", "",
              "Диагностика с фактическим будущим ветром хранится отдельно в `diagnostic.json`; "
              "её результат нельзя выдавать за точность прогноза на 24–48 часов.", "",
              "## Повторить", "", "Из каталога `ml`:", "", "```powershell",
              r".\.venv\Scripts\python.exe scripts/download_weather.py --model icon_global --start 2024-01-01 --end 2026-03-01 --output data/weather/icon/archive.csv",
              r".\.venv\Scripts\python.exe scripts/improve_accuracy.py",
              r".\.venv\Scripts\python.exe scripts/diagnose_accuracy.py",
              r".\.venv\Scripts\python.exe -m wind_forecast.ui --artifact-dir artifacts/accuracy --port 8766", "```", "",
              "Артефакты прежней модели в `artifacts/improved` сохранены. "
              "Новая проверочная и производственная модели находятся в `artifacts/accuracy`. "
              "Вторая переобучена на данных, доступных к 31 января 2026 23:00; для проверки января используется первая.", ""]
    (reports / "report.md").write_text("\n".join(lines), encoding="utf-8")


def learner(spec, trees=300, early_stopping=False):
    if spec["objective"] == "window":
        return WindowRegressor(spec["depth"], trees, early_stopping)
    return build_estimator({"max_depth": spec["depth"], "objective": "reg:absoluteerror",
                            "learning_rate": .04, "min_child_weight": 30, "reg_lambda": 15},
                           trees, early_stopping)


def fit(spec, features, power, masks):
    trial = learner(spec, early_stopping=True)
    trial.fit(features[masks["core"]], power[masks["core"]],
              eval_set=[(features[masks["stopping"]], power[masks["stopping"]])], verbose=False)
    trees = trial.best_iteration + 1
    model = learner(spec, trees)
    model.fit(features[masks["train"]], power[masks["train"]])
    return model, trees


def load_source(path, config, hourly, table):
    weather = read_weather(path)
    config = {**config, "weather_model": str(weather.weather_model.iloc[0])}
    validate_weather(weather, config)
    columns = [c for c in weather if c not in ("power", "issued_at", "horizon_hours")]
    joined = table[KEYS + ["horizon_hours", "power"]].merge(
        weather[columns], on=["valid_time", "turbine_id", "forecast_offset_days"],
        how="left", validate="many_to_one").reset_index(drop=True)
    # Missing weather remains missing; keep every scored target to avoid selecting
    # easier hours. XGBoost can route missing inputs. Report coverage explicitly.
    available = joined.available_at_upper_bound.notna()
    if (joined.loc[available, "available_at_upper_bound"] > joined.loc[available, "issued_at"]).any():
        raise ValueError("Additional weather was unavailable at issuance")
    base = make_features(joined, config["timezone"])
    hist = history_features(hourly, joined, config.get("history"))
    extended = combine_features(base, joined, hist)
    history_columns = list(set(extended) - set(base) - {"horizon_hours"})
    extended.loc[~hist.history_usable, history_columns] = np.nan
    return config, joined, base, extended, hist


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/accuracy")
    parser.add_argument("--report", default="reports/accuracy")
    parser.add_argument("--fresh", action="store_true", help="Retrain all CV models, ignoring cached trials")
    parser.add_argument("--sources", nargs="+", choices=["gfs", "icon", "ensemble"], default=["gfs", "icon", "ensemble"])
    args = parser.parse_args()
    out, reports = Path(args.output), Path(args.report)
    out.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    config, hourly = read_config(), read_hourly()
    table = training_table(hourly, read_weather(), config["timezone"])
    table = table[table.valid_time < as_utc("2026-02-01", config["timezone"])].reset_index(drop=True)
    folds = [chronological_fold(table, start, pd.Timestamp(start) + pd.DateOffset(months=1), config["timezone"])
             for start in DEFAULT_FOLDS]
    old = pd.read_csv("artifacts/improved/cv_predictions.csv", parse_dates=["issued_at", "valid_time"])
    old["prediction"] = .75 * old.weather_prediction + .25 * old.history_prediction
    expected = pd.concat([table.loc[fold["validation"], KEYS] for fold in folds])
    if len(expected.merge(old[KEYS], on=KEYS, validate="one_to_one")) != len(expected) or len(old) != len(expected):
        raise ValueError("CV comparison must use exactly the same forecast rows")
    old_folds = [accuracy_scores(g.power, g.prediction) for _, g in old.groupby("fold")]
    baseline = {"mean_hit_rate_10pp": float(np.mean([g["hit_rate_10pp"] for g in old_folds])),
                "mean_mae": float(np.mean([g["mae"] for g in old_folds])), "folds": old_folds}
    paths = {"gfs": "data/weather/archive.csv", "icon": "data/weather/icon/archive.csv", "ensemble": "data/weather/ensemble/archive.csv"}
    if "ensemble" in args.sources:
        gfs, icon = read_weather(paths["gfs"]), read_weather(paths["icon"])
        validate_weather(icon, {**config, "weather_model": "icon_global"})
        keys = ["valid_time", "turbine_id", "forecast_offset_days"]
        joined = gfs.merge(icon[keys + list(VARIABLES) + ["available_at_upper_bound"]].rename(
            columns={c: f"icon_{c}" for c in [*VARIABLES, "available_at_upper_bound"]}),
            on=keys, how="left", validate="one_to_one")
        if (joined.icon_available_at_upper_bound > joined.available_at_upper_bound).any():
            raise ValueError("Additional weather has a later availability bound")
        joined = joined.drop(columns="icon_available_at_upper_bound")
        Path(paths["ensemble"]).parent.mkdir(parents=True, exist_ok=True)
        joined.to_csv(paths["ensemble"], index=False)
    sources, runs = {}, []
    for source in args.sources:
        sources[source] = load_source(paths[source], config, hourly, table)
        source_config, source_table, base, extended, hist = sources[source]
        digest = hashlib.sha256(b"hit10pp-v2-history-fallback")
        for path in (paths[source], "data/processed/hourly.csv", "config.json", "wind_forecast/accuracy.py"):
            digest.update(Path(path).read_bytes())
        fingerprint = digest.hexdigest()
        candidates = [("window", 5)] if source == "ensemble" else [("absolute", 5), ("window", 3), ("window", 5)]
        for objective, depth in candidates:
            for use_history in (False, True):
                spec = {"source": source, "objective": objective, "depth": depth, "history": use_history}
                name = f"{source}_{objective}_d{depth}_{'history' if use_history else 'weather'}"
                cached = reports / f"{name}.json"
                cached_run = json.loads(cached.read_text(encoding="utf-8")) if cached.exists() else {}
                if not args.fresh and cached_run.get("fingerprint") == fingerprint and (out / f"{name}_cv.csv").exists():
                    runs.append(cached_run)
                    print(f"Cached {name}: {runs[-1]['mean_hit_rate_10pp']:.2%}", flush=True)
                    continue
                features = extended if use_history else base
                metrics, predictions = [], []
                for number, fold in enumerate(folds):
                    model, trees = fit(spec, features, table.power, fold)
                    selected = fold["validation"]
                    pred = np.clip(model.predict(features[selected]), 0, 1)
                    if use_history:
                        fallback_name = name.replace("_history", "_weather")
                        previous = pd.read_csv(out / f"{fallback_name}_cv.csv")
                        fallback = previous.loc[previous.fold == number, "prediction"].to_numpy()
                        usable = hist.loc[selected, "history_usable"].to_numpy()
                        pred[~usable] = fallback[~usable]
                    metrics.append({"start": str(fold["start"]), "trees": trees,
                                    **accuracy_scores(table.loc[selected, "power"], pred)})
                    rows = table.loc[selected, KEYS + ["power"]].copy()
                    rows["prediction"], rows["fold"] = pred, number
                    predictions.append(rows)
                    print(f"{name} fold {number + 1}: hit={metrics[-1]['hit_rate_10pp']:.2%}, MAE={metrics[-1]['mae']:.4f}, trees={trees}", flush=True)
                run = {"name": name, "spec": spec, "folds": metrics, "fingerprint": fingerprint,
                       "mean_hit_rate_10pp": float(np.mean([m["hit_rate_10pp"] for m in metrics])),
                       "mean_mae": float(np.mean([m["mae"] for m in metrics]))}
                pd.concat(predictions).to_csv(out / f"{name}_cv.csv", index=False)
                cached.write_text(json.dumps(run, indent=2), encoding="utf-8")
                runs.append(run)
    best = max(runs, key=lambda run: (run["mean_hit_rate_10pp"], -run["mean_mae"]))
    # Persist the decision BEFORE reading January outcomes or fitting January models.
    decision = {"metric": "fraction abs(prediction-actual)<=0.10 (normalized power)",
                "goal": .8, "baseline_cv": baseline, "selected": best, "runs": runs,
                "selection_period": "2025-01, 2025-05, 2025-09, 2025-11; equal month weights",
                "january_role": "previously inspected regression period, not a new blind test"}
    (reports / "selection.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    spec = best["spec"]
    source_config, source_table, base, extended, hist = sources[spec["source"]]
    features = extended if spec["history"] else base
    trees = int(np.median([fold["trees"] for fold in best["folds"]]))
    weather_run = next(run for run in runs if run["name"] == best["name"].replace("_history", "_weather"))
    weather_trees = int(np.median([fold["trees"] for fold in weather_run["folds"]]))
    cal_start, test_start, test_end = [as_utc(s, config["timezone"]) for s in ("2025-12-01", "2026-01-01", "2026-02-01")]
    completed = table.valid_time + pd.Timedelta(hours=1)
    test = table.valid_time.between(test_start, test_end, inclusive="left")
    fitting = completed <= cal_start
    calibration = table.valid_time.between(cal_start, test_start, inclusive="left") & (table.issued_at >= cal_start)
    calibration &= completed <= table.loc[test, "issued_at"].min()
    model = learner(spec, trees).fit(features[fitting], table.loc[fitting, "power"])
    # A separate weather-only estimator is the operational fallback when SCADA is stale.
    weather_model = learner(spec, weather_trees).fit(base[fitting], table.loc[fitting, "power"]) if spec["history"] else model
    weather_cal = np.clip(weather_model.predict(base[calibration]), 0, 1)
    mixed_cal = weather_cal.copy()
    usable = hist.loc[calibration, "history_usable"].to_numpy()
    if spec["history"]:
        mixed_cal[usable] = np.clip(model.predict(features[calibration & hist.history_usable]), 0, 1)
    bundle = {"schema_version": 2, "config": source_config, "features": list(base), "model": weather_model,
              "interval_offsets": interval_offsets(table[calibration], weather_cal),
              "history_model": model if spec["history"] else None, "history_features": list(extended),
              "history_weight": 1.0, "use_history": spec["history"],
              "history_interval_offsets": interval_offsets(table[calibration], mixed_cal),
              "training_max_valid_time": str(table.loc[fitting, "valid_time"].max()),
              "calibration_max_valid_time": str(table.loc[calibration, "valid_time"].max()),
              "selection_metric": "hit_rate_10pp", "selected_parameters": best,
              "additional_weather_columns": [f"icon_{c}" for c in VARIABLES] if spec["source"] == "ensemble" else [],
              "weather_archive": paths[spec["source"]]}
    joblib.dump(bundle, out / "evaluation_model.joblib")
    regression = source_table[test].copy()
    detail = predict_details(bundle, regression, hourly)
    for column in detail:
        regression[column] = detail[column]
    regression.to_csv(out / "regression_predictions.csv", index=False)
    old_january = pd.read_csv("artifacts/improved/regression_predictions.csv", parse_dates=["issued_at", "valid_time"])
    common = regression.merge(old_january[KEYS + ["prediction"]], on=KEYS, suffixes=("", "_baseline"), validate="one_to_one")
    if len(common) != len(regression) or len(common) != len(old_january):
        raise ValueError("January comparison must score exactly the same forecast rows")
    decision["baseline_january"] = accuracy_scores(common.power, common.prediction_baseline)
    decision["january"] = accuracy_scores(common.power, common.prediction)
    constant = float(CENTERS[WindowRegressor.labels(table.loc[fitting, "power"]).mean(axis=0).argmax()])
    decision["constant_baseline"] = {"prediction": constant,
                                      **accuracy_scores(common.power, np.full(len(common), constant))}
    decision["target_reached"] = decision["january"]["hit_rate_10pp"] >= .8 and best["mean_hit_rate_10pp"] >= .8
    decision["by_turbine_and_day"] = [{"turbine": int(t), "day": int(d - 1), **accuracy_scores(g.power, g.prediction)}
                                       for (t, d), g in regression.groupby(["turbine_id", "forecast_offset_days"])]
    decision["by_actual_power_regime"] = [{"range": name, **accuracy_scores(regression.loc[mask, "power"], regression.loc[mask, "prediction"])}
        for name, mask in (("0..0.2", regression.power <= .2), ("0.2..0.8", regression.power.between(.2, .8, inclusive="neither")),
                           ("0.8..1", regression.power >= .8)) if mask.any()]
    decision["interval_80_coverage"] = float(regression.power.between(regression.lower_80, regression.upper_80).mean())
    decision["weather_complete_fraction_january"] = float(regression[list(VARIABLES) + bundle["additional_weather_columns"]].notna().all(axis=1).mean())
    production = completed <= test_end - pd.Timedelta(hours=1)
    bundle["model"] = learner(spec, weather_trees).fit(base[production], table.loc[production, "power"])
    if spec["history"]:
        bundle["history_model"] = learner(spec, trees).fit(extended[production], table.loc[production, "power"])
    bundle["training_max_valid_time"] = str(table.loc[production, "valid_time"].max())
    joblib.dump(bundle, out / "model.joblib")
    write_report(decision, regression, reports)
    (reports / "metrics.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    print(json.dumps({"selected": best["name"], "cv_hit": best["mean_hit_rate_10pp"],
                      "january": decision["january"], "target_reached": decision["target_reached"]}, indent=2), flush=True)


if __name__ == "__main__":
    main()
