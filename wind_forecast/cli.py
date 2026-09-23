import argparse
import json
import time

import joblib
from .data import prepare_data, read_config, read_hourly
from .forecast import forecast, replay, save_forecast
from .model import train
from .weather import fetch_archive, read_weather


def main():
    parser = argparse.ArgumentParser(description="HackAlem hourly wind-power forecasting")
    parser.add_argument("--config", default="config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    prepare = commands.add_parser("prepare", help="Aggregate SCADA CSVs to complete hourly targets")
    prepare.add_argument("--turbine-1", required=True)
    prepare.add_argument("--turbine-2", required=True)
    prepare.add_argument("--output-dir", default="data/processed")
    weather = commands.add_parser("fetch-weather", help="Download archived forecasts (requires network)")
    weather.add_argument("--start", default="2024-01-01")
    weather.add_argument("--end", default="2026-03-01")
    weather.add_argument("--output", default="data/weather/archive.csv")
    weather.add_argument("--refresh", action="store_true")
    training = commands.add_parser("train", help="Select, evaluate and save the production model")
    training.add_argument("--hourly", default="data/processed/hourly.csv")
    training.add_argument("--weather", default="data/weather/archive.csv")
    training.add_argument("--artifact-dir", default="artifacts")
    training.add_argument("--report-dir", default="reports")
    for name in ("forecast", "replay", "agent"):
        command = commands.add_parser(name)
        command.add_argument("--model", default="artifacts/model.joblib")
        command.add_argument("--output-dir", default=f"outputs/{'february' if name == 'replay' else name}")
        if name != "agent":
            command.add_argument("--weather", default="data/weather/archive.csv")
        if name == "replay":
            command.add_argument("--start", default="2026-02-01")
            command.add_argument("--end", default="2026-02-28")
        else:
            command.add_argument("--issued-at", required=True, help="ISO timestamp; naive values use model timezone")
            command.add_argument("--horizon", type=int, choices=(24, 48), default=48)
        if name == "agent":
            command.add_argument("--watch-seconds", type=int, default=0, help="Poll this issue for weather updates; 0 = one run")
            command.add_argument("--offline", action="store_true", help="Use an existing HTTP cache")
    args = parser.parse_args()
    if args.command == "prepare":
        _, profiles = prepare_data([args.turbine_1, args.turbine_2], read_config(args.config), args.output_dir)
        print(json.dumps(profiles, indent=2))
    elif args.command == "fetch-weather":
        frame = fetch_archive(read_config(args.config), args.start, args.end, args.output, args.refresh)
        print(f"Saved {len(frame)} rows")
    elif args.command == "train":
        train(read_hourly(args.hourly), read_weather(args.weather), read_config(args.config), args.artifact_dir, args.report_dir)
    elif args.command == "forecast":
        bundle = joblib.load(args.model)
        frame = forecast(bundle, read_weather(args.weather), args.issued_at, args.horizon)
        save_forecast(frame, bundle["config"], args.output_dir)
        print(f"Saved {len(frame)} forecast rows to {args.output_dir}")
    elif args.command == "replay":
        frame = replay(joblib.load(args.model), read_weather(args.weather), args.start, args.end, args.output_dir)
        print(f"Saved {len(frame)} submission rows to {args.output_dir}")
    elif args.command == "agent":
        from .agent import run_agent
        if args.watch_seconds < 0 or (args.watch_seconds and args.watch_seconds < 60):
            parser.error("--watch-seconds must be 0 or >=60")
        while True:
            print(json.dumps(run_agent(args.model, args.issued_at, args.output_dir, args.horizon, refresh=not args.offline), indent=2), flush=True)
            if not args.watch_seconds:
                break
            time.sleep(args.watch_seconds)
