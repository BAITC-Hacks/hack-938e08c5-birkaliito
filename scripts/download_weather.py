"""Fetch only public weather forecasts. Never uploads SCADA data."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from wind_forecast.data import read_config
from wind_forecast.weather import fetch_archive

parser = argparse.ArgumentParser()
parser.add_argument("--start", default="2024-01-01")
parser.add_argument("--end", default="2026-03-01")
parser.add_argument("--output", default="data/weather/archive.csv")
args = parser.parse_args()
frame = fetch_archive(read_config(), args.start, args.end, args.output)
print(f"Saved {len(frame)} archived forecast rows to {args.output}")
