import pandas as pd
import pytest

from wind_forecast.evaluation import evaluate


def inputs():
    predictions = pd.DataFrame({"issued_at": ["2026-01-31T23:00Z"] * 3,
                                "valid_time": pd.date_range("2026-02-01", periods=3, freq="h", tz="UTC"),
                                "turbine_id": 1, "prediction": [0.2, 0.6, 0.9]})
    actual = predictions[["valid_time", "turbine_id"]].assign(power=[0.3, 0.4, float("nan")])
    return predictions, actual


def test_evaluation_reports_errors_and_missing_target_coverage(tmp_path):
    predictions, actual = inputs()
    report = evaluate(predictions, actual, tmp_path)
    assert report["metrics"]["mae"] == pytest.approx(0.15)
    assert report["target_coverage"] == pytest.approx(2 / 3)
    assert report["scored_rows"] == 2
    assert report["missing_or_invalid_actual_rows"] == 1
    assert len(pd.read_csv(tmp_path / "predictions_vs_actual.csv")) == 2


def test_evaluation_rejects_duplicated_forecasts(tmp_path):
    predictions, actual = inputs()
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate(pd.concat([predictions, predictions]), actual, tmp_path)


def test_evaluation_requires_matching_real_targets(tmp_path):
    predictions, actual = inputs()
    with pytest.raises(ValueError, match="No complete actual"):
        evaluate(predictions, actual.assign(power=float("nan")), tmp_path)
