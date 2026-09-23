"""Deterministic forecast workflow with tools, state, checks, and update detection.

This is an explicit state machine, not an LLM-based agent. Each invocation checks
external weather, recomputes changed inputs, validates outputs and writes an audit.
"""

import hashlib
import json
from pathlib import Path

import joblib
import pandas as pd

from .features import as_utc
from .forecast import analysis_report, forecast, save_forecast
from .weather import fetch_archive


def run_agent(model_path, issued_at, output_dir="outputs/agent", horizon=48, refresh=True):
    bundle = joblib.load(model_path)
    config = bundle["config"]
    origin = as_utc(issued_at, config["timezone"])
    first, last = origin + pd.Timedelta(hours=1), origin + pd.Timedelta(hours=horizon)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    events = [{"step": "fetch_weather", "status": "started"}]
    weather = fetch_archive(config, first.strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d"), output / "weather.csv", refresh=refresh, cache_only=not refresh)
    signature = hashlib.sha256(Path(model_path).read_bytes() + weather.to_csv(index=False).encode() + str(origin).encode() + str(horizon).encode()).hexdigest()
    state_file = output / "state.json"
    previous = json.loads(state_file.read_text()) if state_file.exists() else {}
    if previous.get("input_sha256") == signature and (output / "turbines.csv").exists() and (output / "farm.csv").exists():
        return {"status": "unchanged", "issued_at": str(origin), "input_sha256": signature}
    events.append({"step": "check_availability_and_predict", "status": "started"})
    predictions = forecast(bundle, weather, origin, horizon)
    analysis = analysis_report(predictions)
    events.append({"step": "analyze", "status": "passed", **analysis})
    save_forecast(predictions, config, output)
    state = {"status": "updated", "issued_at": str(origin), "input_sha256": signature,
             "processed_at": pd.Timestamp.now(tz="UTC").isoformat(), "events": events}
    state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return state
