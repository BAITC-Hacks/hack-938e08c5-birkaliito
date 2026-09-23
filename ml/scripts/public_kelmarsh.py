"""Retrieve a selected open Kelmarsh SCADA member without downloading 705 MB.

Source: Plumley & Takeuchi, Cubico, https://doi.org/10.5281/zenodo.16807551,
CC BY 4.0. HTTP ranges are verified; no access credentials are required.
"""

import argparse
import csv
import hashlib
import io
import json
import sys
import time
import zipfile
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

BASE = "https://zenodo.org/records/16807551/files/"
ARCHIVE = "Kelmarsh_SCADA_2024_5962.zip"
OUTPUT = ROOT / "data" / "raw" / "kelmarsh"


def request(url, headers=None):
    for attempt in range(4):
        try:
            return urlopen(Request(url, headers={"User-Agent": "WindForecast-OpenDataValidation/0.1", **(headers or {})}), timeout=90)
        except HTTPError as exc:
            if exc.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


class RangeReader(io.RawIOBase):
    def __init__(self, url):
        self.url, self.position = url, 0
        with request(url, {"Range": "bytes=-65536"}) as response:
            if response.status != 206:
                raise ValueError("Server does not support partial download")
            self.size = int(response.headers["Content-Range"].split("/")[-1])
            self.tail = response.read()
        self.tail_start = self.size - len(self.tail)
        self.block, self.block_start, self.downloaded = b"", 0, len(self.tail)

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        self.position = offset if whence == 0 else self.position + offset if whence == 1 else self.size + offset
        if self.position < 0:
            raise ValueError("Negative seek")
        return self.position

    def read(self, count=-1):
        if count < 0:
            count = self.size - self.position
        count = min(count, self.size - self.position)
        parts = []
        while count > 0:
            if self.position >= self.tail_start:
                piece = self.tail[self.position - self.tail_start:self.position - self.tail_start + count]
            else:
                if not self.block_start <= self.position < self.block_start + len(self.block):
                    self.block_start = self.position
                    end = min(self.position + 8 * 1024 * 1024 - 1, self.size - 1)
                    cache = OUTPUT / "ranges" / f"{self.size}_{self.position}_{end}.bin"
                    if cache.exists():
                        self.block = cache.read_bytes()
                    else:
                        with request(self.url, {"Range": f"bytes={self.position}-{end}"}) as response:
                            expected = f"bytes {self.position}-{end}/{self.size}"
                            if response.status != 206 or response.headers.get("Content-Range") != expected:
                                raise ValueError(f"Unexpected range response: {response.headers.get('Content-Range')}")
                            self.block = response.read()
                        if len(self.block) != end - self.position + 1:
                            raise EOFError("Incomplete public archive range")
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        temporary = cache.with_suffix(".tmp")
                        temporary.write_bytes(self.block)
                        temporary.replace(cache)
                    self.downloaded += len(self.block)
                    print(f"Downloaded {self.downloaded / 1024**2:.1f} MiB of selected member", flush=True)
                offset = self.position - self.block_start
                piece = self.block[offset:offset + count]
            if not piece:
                raise EOFError("Unexpected end of public archive")
            parts.append(piece)
            count -= len(piece)
            self.position += len(piece)
        return b"".join(parts)


def download_scada(inspect=False):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    static_path = OUTPUT / "static.csv"
    if not static_path.exists():
        with request(BASE + "Kelmarsh_WT_static.csv?download=1") as response:
            static_path.write_bytes(response.read())
    with RangeReader(BASE + ARCHIVE + "?download=1") as remote, zipfile.ZipFile(remote) as archive:
        members = [item for item in archive.infolist() if item.filename.startswith("Turbine_Data_Kelmarsh_1_")]
        if len(members) != 1:
            raise ValueError("Expected exactly one turbine 1 SCADA member")
        member = members[0]
        print(json.dumps({"member": member.filename, "compressed_bytes": member.compress_size, "uncompressed_bytes": member.file_size}))
        with archive.open(member) as stream:
            source = io.TextIOWrapper(stream, encoding="utf-8-sig")
            metadata = [source.readline().rstrip() for _ in range(9)]
            if "# Time zone: UTC" not in metadata:
                raise ValueError("Unexpected SCADA timezone")
            columns = next(csv.reader([source.readline()]))
            wanted = [name for name in columns if name == "# Date and time" or name == "Power (kW)"
                      or name == "Wind speed (m/s)" or name.startswith("Nacelle ambient temperature (")]
            print(json.dumps({"selected_columns": wanted, "total_columns": len(columns)}), flush=True)
            if inspect:
                import pandas as pd
                sample = pd.read_csv(source, names=columns, usecols=wanted, nrows=20000)
                stamps = pd.to_datetime(sample["# Date and time"], utc=True, errors="coerce")
                print(sample.head(3).to_string(index=False))
                print(sample.tail(3).to_string(index=False))
                print(stamps.diff().value_counts().head(8).to_string())
                return
            if len(wanted) != 4:
                raise ValueError("Expected timestamp, active power, wind speed and ambient temperature")
            import pandas as pd
            chunks = []
            for chunk in pd.read_csv(source, names=columns, usecols=wanted, chunksize=4096):
                chunks.append(chunk)
                if len(chunks) % 8 == 0:
                    print(f"Parsed {sum(len(c) for c in chunks)} source records", flush=True)
            selected = pd.concat(chunks, ignore_index=True)
            target = OUTPUT / "turbine_1_2024_selected.csv"
            selected.to_csv(target, index=False)
            provenance = {"source": "https://zenodo.org/records/16807551", "license": "CC BY 4.0",
                          "authors": "Charlie Plumley and Roberta Takeuchi / Cubico",
                          "archive": ARCHIVE, "member": member.filename, "member_crc32": f"{member.CRC:08x}",
                          "member_crc_checked_by_zipfile": True, "metadata": metadata,
                          "selected_columns": wanted, "records": len(selected),
                          "selected_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                          "retrieved_at": pd.Timestamp.now(tz="UTC").isoformat()}
            (OUTPUT / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
            print(f"Saved {target}", flush=True)


def external_config(model_path):
    import copy
    import joblib
    import pandas as pd

    bundle = joblib.load(model_path)
    config = copy.deepcopy(bundle["config"])
    static = pd.read_csv(OUTPUT / "static.csv").set_index("Title").loc["Kelmarsh 1"]
    config["timezone"] = "Europe/London"
    config["turbines"] = [{"id": 1, "latitude": float(static.Latitude),
                           "longitude": float(static.Longitude),
                           "rated_power_mw": float(static["Rated power (kW)"]) / 1000}]
    return bundle, config


def prepare_hourly(source, rated_kw):
    """Coalesce sparse repeated timestamps, then require six power samples/hour.

    The Greenbyte export repeats timestamps in sparse blocks. Different values
    for the same signal/time are rejected, not silently averaged or selected.
    """
    import numpy as np
    import pandas as pd

    temperature = [name for name in source if name.startswith("Nacelle ambient temperature (")]
    if len(temperature) != 1 or rated_kw <= 0:
        raise ValueError("Expected one ambient temperature and positive rated kW")
    frame = source.rename(columns={"# Date and time": "valid_time", "Power (kW)": "power_kw",
                                   "Wind speed (m/s)": "wind_speed", temperature[0]: "temperature"}).copy()
    frame["valid_time"] = pd.to_datetime(frame.valid_time, utc=True, errors="raise")
    if frame.valid_time.isna().any() or not frame.valid_time.eq(frame.valid_time.dt.floor("10min")).all():
        raise ValueError("Expected exact ten-minute UTC timestamps")
    signals = ["power_kw", "wind_speed", "temperature"]
    frame[signals] = frame[signals].apply(pd.to_numeric, errors="raise")
    frame[signals] = frame[signals].replace([np.inf, -np.inf], np.nan)
    grouped = frame.groupby("valid_time", sort=True)[signals]
    conflicts = grouped.nunique(dropna=True).gt(1)
    if conflicts.any().any():
        raise ValueError(f"Conflicting duplicate SCADA measurements: {conflicts.sum().to_dict()}")
    compact = grouped.first()
    grouped_hour = compact.resample("h")
    counts = grouped_hour.count()
    hourly = grouped_hour.mean().where(counts >= 6)
    hourly["power_raw_normalized"] = hourly.power_kw / rated_kw
    hourly["power"] = hourly.power_raw_normalized.clip(0, 1)
    hourly["turbine_id"] = 1
    hourly = hourly.reset_index()
    hourly["samples"] = counts.power_kw.to_numpy()
    quality = {"source_rows": len(frame), "unique_timestamps": len(compact),
               "duplicate_timestamp_rows": int(frame.duplicated("valid_time").sum()),
               "rows_with_all_selected_signals_missing": int(frame[signals].isna().all(axis=1).sum()),
               "conflicting_duplicates": 0, "complete_power_hours": int(hourly.power.notna().sum()),
               "incomplete_power_hours": int(hourly.power.isna().sum()),
               "negative_power_hours_clipped": int((hourly.power_raw_normalized < 0).sum()),
               "over_rated_power_hours_clipped": int((hourly.power_raw_normalized > 1).sum()),
               "hourly_raw_normalized_min": float(hourly.power_raw_normalized.min()),
               "hourly_raw_normalized_max": float(hourly.power_raw_normalized.max())}
    return hourly, quality


def evaluate_public(model_path):
    """Frozen spatial transfer, deliberately NOT an as-of-2024 backtest.

    The production artifact learned Kazakh data through Jan 2026. Only the
    external location/calendar metadata changes. No fit, calibration or model
    selection is performed using Kelmarsh. The production forecast time guard
    remains intact; here we call the predictor for this explicit transfer test.
    """
    import numpy as np
    import pandas as pd
    from wind_forecast.features import training_table
    from wind_forecast.history import history_features
    from wind_forecast.model import predict_details, scores
    from wind_forecast.weather import read_weather, validate_weather, VARIABLES

    model_path = Path(model_path)
    before_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    bundle, config = external_config(model_path)
    original_training_end = bundle["training_max_valid_time"]
    bundle = {**bundle, "config": config}
    source_path = OUTPUT / "turbine_1_2024_selected.csv"
    provenance = json.loads((OUTPUT / "provenance.json").read_text(encoding="utf-8"))
    if hashlib.sha256(source_path.read_bytes()).hexdigest() != provenance["selected_sha256"]:
        raise ValueError("Selected SCADA file no longer matches the downloaded source checksum")
    source = pd.read_csv(source_path)
    hourly, quality = prepare_hourly(source, config["turbines"][0]["rated_power_mw"] * 1000)
    weather = read_weather("data/weather/kelmarsh/archive.csv")
    validate_weather(weather, config)
    start, end = pd.Timestamp("2024-01-01", tz="UTC"), pd.Timestamp("2025-01-01", tz="UTC")
    hourly = hourly[hourly.valid_time.between(start, end, inclusive="left")].copy()
    weather = weather[weather.valid_time.between(start, end, inclusive="left")].copy()
    # Fixed 23:00 UTC issuance avoids variable 23/25-hour civil days. Calendar
    # features use Europe/London, appropriate to the external station.
    table = training_table(hourly, weather, "UTC")
    if table.empty:
        raise ValueError("No real targets match complete archived weather")
    actual = table.pop("power")  # Never pass the target into the model.
    details = predict_details(bundle, table, hourly)
    weather_only = predict_details({**bundle, "use_history": False}, table)
    history = history_features(hourly, table, config.get("history"))
    matched = pd.concat([table[["valid_time", "issued_at", "horizon_hours", "forecast_offset_days"]], details], axis=1)
    matched["actual"] = actual
    matched["weather_only"] = weather_only.prediction
    matched["persistence"] = history.observed_power_last.where(history.history_usable)
    matched["day"] = np.where(matched.horizon_hours <= 24, 1, 2)
    raw = hourly.set_index("valid_time").power_raw_normalized
    matched["actual_raw"] = matched.valid_time.map(raw)
    matched["absolute_error"] = (matched.actual - matched.prediction).abs()
    common = matched[matched.persistence.notna()]
    if common.empty:
        raise ValueError("No rows with fresh persistence observations")
    modes = {"current_blend": scores(matched.actual, matched.prediction),
             "weather_only": scores(matched.actual, matched.weather_only)}
    baseline = {"rows": len(common), "current_blend": scores(common.actual, common.prediction),
                "persistence": scores(common.actual, common.persistence)}
    baseline["blend_mae_skill_vs_persistence"] = 1 - baseline["current_blend"]["mae"] / baseline["persistence"]["mae"]
    by_horizon = [{"day": int(day), "rows": len(part), **scores(part.actual, part.prediction)}
                  for day, part in matched.groupby("day")]
    by_month = [{"month": str(month), "rows": len(part), **scores(part.actual, part.prediction)}
                for month, part in matched.groupby(matched.valid_time.dt.strftime("%Y-%m"))]
    after_hash = hashlib.sha256(model_path.read_bytes()).hexdigest()
    if before_hash != after_hash:
        raise RuntimeError("Production model file changed during scoring")
    expected = 366 * 24 * 2
    report = {"evaluation_type": "retrospective spatial transfer, NOT an operational 2024 backtest",
              "source": provenance,
              "weather_source": "https://open-meteo.com/en/docs/previous-runs-api",
              "test_period_utc": [str(start), str(end)], "end_exclusive": True,
              "model_path": str(model_path), "model_sha256_before": before_hash,
              "model_sha256_after": after_hash, "model_training_max_valid_time": original_training_end,
              "model_refit_or_selection_on_external_data": False, "config_for_external_test": config,
              "turbine_id_mapping": "Kelmarsh 1 -> existing Kazakh turbine_id=1 (unadapted transfer assumption)",
              "nominal_power_kw": 2050, "normalization": "clip(mean_hourly_active_power_kw / 2050, 0, 1)",
              "time_alignment": "SCADA timestamps assumed interval starts; completed hour usable one hour later",
              "issuance": "daily 23:00 UTC; horizons 1..48 hours; calendar features Europe/London",
              "weather_protocol": "GFS previous_day2/day3; conservative 6h publication allowance; no exact run IDs",
              "planned_forecast_rows": expected, "scored_rows": len(matched),
              "first_scored_target": str(matched.valid_time.min()),
              "last_scored_target": str(matched.valid_time.max()),
              "unique_target_hours": int(matched.valid_time.nunique()),
              "scored_fraction_of_full_year": len(matched) / expected,
              "weather_rows_with_any_missing_variable": int(weather[list(VARIABLES)].isna().any(axis=1).sum()),
              "quality": quality, "metrics": modes, "baseline_common_rows": baseline,
              "unclipped_target_metrics": scores(matched.actual_raw, matched.prediction),
              "by_horizon": by_horizon, "by_month": by_month,
              "history_used_fraction": float(details.prediction_mode.eq("weather_and_history").mean()),
              "interval_80_coverage": float(matched.actual.between(matched.lower_80, matched.upper_80).mean()),
              "interval_warning": "Intervals were calibrated on Kazakhstan, not Kelmarsh",
              "limitations": ["Different station, turbine type, terrain and normalization from the case",
                              "Only one external turbine; overlapping day-1/day-2 targets are not independent samples",
                              "Weights learned through Jan 2026: spatial transfer only, not a historical deployment claim",
                              "Original case power normalization formula/rated turbine powers remain unconfirmed"],
              "created_at": pd.Timestamp.now(tz="UTC").isoformat()}
    output = ROOT / "outputs" / "public_kelmarsh"
    output.mkdir(parents=True, exist_ok=True)
    matched.to_csv(output / "predictions_vs_actual.csv", index=False)
    hourly.to_csv(output / "hourly.csv", index=False)
    reports = ROOT / "reports" / "public_validation"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "metrics.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    pd.DataFrame(by_month).to_csv(reports / "monthly.csv", index=False)
    write_report(report, reports / "report.md")
    print(json.dumps({"rows": len(matched), "metrics": modes, "baseline": baseline,
                      "quality": quality, "by_horizon": by_horizon}, indent=2), flush=True)
    return report


def write_report(report, path):
    quality = report["quality"]
    metrics = report["metrics"]["current_blend"]
    baseline = report["baseline_common_rows"]
    lines = ["# Проверка готовой модели на открытых данных Kelmarsh", "",
             "Это ретроспективная проверка переноса модели на другую станцию. "
             "Модель обучалась на данных казахстанских турбин до января 2026, поэтому "
             "этот эксперимент нельзя считать воспроизведением реального прогноза в 2024 году. "
             "Измерения Kelmarsh не использовались для обучения, выбора параметров или калибровки.", "",
             "Источники: [Kelmarsh / Cubico, Plumley & Takeuchi, Zenodo v4](https://zenodo.org/records/16807551), "
             "лицензия CC BY 4.0; [архив прогнозов NOAA GFS через Open-Meteo](https://open-meteo.com/en/docs/previous-runs-api).", "",
             "## Результат", "",
             "| Модель / горизонт | MAE | RMSE | R² |", "|---|---:|---:|---:|"]
    for title, values in [("Текущая комбинация, 1–48 ч", metrics),
                          ("Только погода, 1–48 ч", report["metrics"]["weather_only"])]:
        lines.append(f"| {title} | {values['mae']:.4f} | {values['rmse']:.4f} | {values['r2']:.4f} |")
    for row in report["by_horizon"]:
        title = "Текущая комбинация, " + ("1–24 ч" if row["day"] == 1 else "25–48 ч")
        lines.append(f"| {title} | {row['mae']:.4f} | {row['rmse']:.4f} | {row['r2']:.4f} |")
    lines += ["", f"MAE {metrics['mae']:.4f} — ошибка {100 * metrics['mae']:.2f} процентного пункта "
              "номинальной мощности, а не процент правильных ответов.", "",
              f"Проверены **{report['scored_rows']}** прогнозов для **{report['unique_target_hours']}** уникальных часов. "
              f"Охват — **{report['scored_fraction_of_full_year']:.2%}** от 17 568 запланированных прогнозов за весь 2024 год. "
              f"Фактически оценённые цели: `{report['first_scored_target']}` — `{report['last_scored_target']}`. "
              "Январь и часть февраля отсутствуют в оценке из-за неполного архива погодных признаков; "
              "значения не интерполируются. Первый и второй день имеют перекрывающиеся цели и не являются независимыми выборками.", "",
              f"На одинаковых {baseline['rows']} строках с доступной свежей историей: "
              f"MAE модели **{baseline['current_blend']['mae']:.4f}**, "
              f"переноса последней полной часовой мощности — **{baseline['persistence']['mae']:.4f}**. "
              f"Снижение MAE — **{baseline['blend_mae_skill_vs_persistence']:.1%}**.", "",
              "## Протокол и качество данных", "",
              "- Одна турбина Kelmarsh 1, Senvion MM92, номинал 2050 кВт, координаты 52.400604, -0.947133. "
              "В готовой модели условно используется существующий `turbine_id=1`: специального обучения под новую турбину нет.",
              "- Нормализация: средняя измеренная активная мощность за полный час / 2050, с ограничением 0…1. "
              "Остановы и нулевая генерация остаются в оценке. Сохраняется также метрика без ограничения факта.",
              f"- Из {quality['source_rows']} строк получено {quality['unique_timestamps']} уникальных 10-минутных меток. "
              f"Повторов меток: {quality['duplicate_timestamp_rows']}; противоречивых значений: 0. "
              "Повторные разреженные строки объединяются по каждому сигналу, без умножения веса наблюдений.",
              f"- Полных часов мощности: {quality['complete_power_hours']}; неполных: {quality['incomplete_power_hours']}. "
              "Для часа нужны шесть разных 10-минутных измерений; пропуски не заполняются.",
              f"- Часов с небольшой отрицательной мощностью: {quality['negative_power_hours_clipped']}; "
              f"выше номинала: {quality['over_rated_power_hours_clipped']}. "
              f"Диапазон до ограничения: {quality['hourly_raw_normalized_min']:.6f}…{quality['hourly_raw_normalized_max']:.6f}. "
              f"MAE без ограничения факта: {report['unclipped_target_metrics']['mae']:.6f}.",
              "- Метки SCADA — UTC, интерпретируются как начало интервала. Полный час доступен после его завершения. "
              "Выпуски каждый день в 23:00 UTC; календарные признаки — Europe/London. Настройки Asia/Almaty для основной ВЭС не изменены.",
              "- Входы: архивные прогнозы GFS предыдущих суток 2/3 и завершённые прошлые измерения. "
              "Будущая фактическая погода и будущая мощность не используются. "
              "Проверяется консервативная доступность с запасом 6 ч; точных идентификаторов метеовыпусков в этом API нет.",
              f"- Свежая история использована в {report['history_used_fraction']:.2%} строк. "
              f"Покрытие перенесённого 80% интервала: {report['interval_80_coverage']:.2%}; "
              "калибровка сделана в Казахстане и не гарантирует такое же покрытие на других ВЭС.",
              "- Тип турбины, климат, рельеф и формула исходной нормализации отличаются. "
              "Этот результат не заменяет проверку новых фактических измерений двух турбин из кейса.", "",
              "## Воспроизведение", "", "Из корня проекта в PowerShell:", "", "```powershell",
              ".\\.venv\\Scripts\\python.exe scripts/public_kelmarsh.py",
              "# Повторная оценка из локальных файлов, без сети и обучения:",
              ".\\.venv\\Scripts\\python.exe scripts/public_kelmarsh.py --stage evaluate", "```", "",
              "Нужен существующий `artifacts/improved/model.joblib`. Первый запуск читает около 120 МиБ "
              "сжатого архива диапазонами HTTP и сохраняет только выбранные сигналы. "
              "Полный CSV на 2,9 ГБ не распаковывается на диск. CRC выбранного ZIP-файла проверяется при чтении.", "",
              f"SHA-256 модели до и после проверки одинаков: `{report['model_sha256_before']}`. "
              f"Последняя обучающая цель: `{report['model_training_max_valid_time']}`.", "",
              "Подробности: [metrics.json](metrics.json), [метрики по месяцам](monthly.csv). "
              "Прогнозы и факт: `outputs/public_kelmarsh/predictions_vs_actual.csv`. "
              "Скачанные SCADA и погода хранятся локально в игнорируемом Git каталоге `data/`."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--inspect", action="store_true")
    parser.add_argument("--stage", choices=("download", "weather", "evaluate", "all"), default="all")
    parser.add_argument("--model", default="artifacts/improved/model.joblib")
    args = parser.parse_args()
    if args.inspect:
        download_scada(inspect=True)
        return
    if args.stage in ("download", "all") and not all((OUTPUT / name).exists() for name in
                                                   ("provenance.json", "turbine_1_2024_selected.csv", "static.csv")):
        download_scada()
    if args.stage in ("weather", "all"):
        from wind_forecast.weather import fetch_archive
        _, config = external_config(args.model)
        fetch_archive(config, "2024-01-01", "2024-12-31", "data/weather/kelmarsh/archive.csv")
    if args.stage in ("evaluate", "all"):
        evaluate_public(args.model)


if __name__ == "__main__":
    main()
