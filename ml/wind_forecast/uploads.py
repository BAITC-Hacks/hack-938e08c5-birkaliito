"""Validate user-supplied CSV content without trusting filenames or paths."""

import csv
import io

import numpy as np
import pandas as pd

from .data import COLUMN_MAP, load_turbine
from .features import as_utc

MAX_CSV_BYTES = 16 * 1024 * 1024
FIELD_LIMITS = {
    "wind_speed_10m": (0, 60), "wind_speed_100m": (0, 60),
    "wind_direction_100m": (0, 360), "temperature_2m": (-60, 60),
    "surface_pressure": (500, 1100),
}


def utc_column(series, timezone, name):
    try:
        values = series.map(lambda value: as_utc(value, timezone))
        stamps = pd.to_datetime(values, utc=True)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError(f"Столбец {name}: некорректное время. Используйте YYYY-MM-DD HH:MM или ISO с часовым поясом.") from exc
    if stamps.isna().any() or not stamps.eq(stamps.dt.floor("h")).all():
        raise ValueError(f"Столбец {name}: нужны непустые метки ровно на начало часа.")
    return stamps


def parse_upload(text, timezone):
    if not isinstance(text, str) or not text.strip():
        raise ValueError("Выберите непустой CSV-файл.")
    if len(text.encode("utf-8")) > MAX_CSV_BYTES:
        raise ValueError("CSV слишком большой: максимальный размер 16 МиБ.")
    text = text.lstrip("\ufeff")
    try:
        try:
            delimiter = csv.Sniffer().sniff(text[:8192], delimiters=",;\t").delimiter
        except csv.Error:
            # A malformed data row should report its row number, not hide the
            # delimiter that is unambiguous in the header.
            delimiter = csv.Sniffer().sniff(text.splitlines()[0], delimiters=",;\t").delimiter
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        headers = [name.strip() for name in next(reader)]
        if len(headers) != len(set(headers)):
            raise ValueError("В заголовке CSV повторяются названия столбцов.")
        for row_number, row in enumerate(reader, 2):
            if row and len(row) != len(headers):
                raise ValueError(f"Строка {row_number}: число значений не совпадает с заголовком CSV.")
        frame = pd.read_csv(io.StringIO(text), sep=delimiter, dtype=str, keep_default_na=False, nrows=250001)
    except (csv.Error, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
        raise ValueError("Не удалось прочитать CSV. Поддерживаются разделители: запятая, точка с запятой и табуляция.") from exc
    if not 1 <= len(frame) <= 250000:
        raise ValueError("В CSV должно быть от 1 до 250 000 строк данных.")
    frame.columns = headers
    for name in frame:
        frame[name] = frame[name].str.strip()
    if set(COLUMN_MAP) <= set(frame) or {"timestamp", "power", "wind_speed", "temperature"} <= set(frame):
        frame = frame.rename(columns=COLUMN_MAP)
        for name in ("power", "wind_speed", "temperature"):
            frame[name] = frame[name].str.replace(",", ".", regex=False)
        try:
            stamps = pd.to_datetime(frame.timestamp, format="mixed", errors="raise")
            if stamps.isna().any() or stamps.max() - stamps.min() > pd.Timedelta(days=3660):
                raise ValueError("Нужны непустые временные метки с диапазоном не более 10 лет.")
            hourly, profile = load_turbine(io.StringIO(frame.to_csv(index=False)), 1, timezone)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Некорректный CSV турбины: {exc}") from exc
        return {"kind": "scada", "frame": hourly, "source_rows": len(frame), "profile": profile}
    required = {"valid_time", *FIELD_LIMITS}
    missing = required - set(frame)
    if missing:
        raise ValueError("Не распознан формат CSV. Для погоды не хватает столбцов: " + ", ".join(sorted(missing))
                         + ". Скачайте шаблон или выберите исходный CSV турбины из кейса.")
    frame["valid_time"] = utc_column(frame.valid_time, timezone, "valid_time")
    for name, (low, high) in FIELD_LIMITS.items():
        values = pd.to_numeric(frame[name].str.replace(",", ".", regex=False), errors="coerce")
        invalid = ~np.isfinite(values) | ~values.between(low, high)
        if invalid.any():
            row = int(np.flatnonzero(invalid.to_numpy())[0]) + 2
            raise ValueError(f"Строка {row}, {name}: нужно число в диапазоне {low}…{high}.")
        frame[name] = values
    keys = ["valid_time"]
    if "turbine_id" in frame:
        ids = pd.to_numeric(frame.turbine_id, errors="coerce")
        if not ids.isin([1, 2]).all():
            raise ValueError("turbine_id должен быть 1 или 2; либо удалите столбец и выберите турбину в форме.")
        frame["turbine_id"] = ids.astype(int)
        keys.append("turbine_id")
    if frame.duplicated(keys).any():
        raise ValueError("В CSV повторяется час для одной турбины. Оставьте один прогноз на каждый час.")
    if "actual_power" in frame:
        empty = frame.actual_power.eq("")
        values = pd.to_numeric(frame.actual_power.str.replace(",", ".", regex=False), errors="coerce")
        if (~empty & (~np.isfinite(values) | ~values.between(0, 1))).any():
            raise ValueError("actual_power: фактическая нормализованная мощность должна быть от 0 до 1; неизвестное оставьте пустым.")
        frame["actual"] = values
    else:
        frame["actual"] = np.nan
    if "issued_at" in frame:
        frame["weather_issued_at"] = utc_column(frame.issued_at, timezone, "issued_at")
        if (frame.weather_issued_at >= frame.valid_time).any():
            raise ValueError("issued_at погоды должен быть раньше valid_time.")
    # Drop unrecognised columns, including any user-supplied model metadata.
    columns = ["valid_time", *FIELD_LIMITS, "actual"]
    columns += [name for name in ("turbine_id", "weather_issued_at") if name in frame]
    return {"kind": "weather", "frame": frame[columns].sort_values("valid_time").reset_index(drop=True),
            "source_rows": len(frame)}


def weather_template():
    frame = pd.DataFrame({"valid_time": pd.date_range("2026-02-01", periods=48, freq="h").strftime("%Y-%m-%d %H:%M"),
                          "wind_speed_10m": 5.0, "wind_speed_100m": 8.0, "wind_direction_100m": 270,
                          "temperature_2m": 5.0, "surface_pressure": 930, "actual_power": ""})
    return frame.to_csv(index=False).encode("utf-8-sig")
