"""Estimators and metrics for hourly predictions within a fixed power tolerance."""

import numpy as np
from xgboost import XGBRegressor

from .model import scores

TOLERANCE = 0.10
CENTERS = np.round(np.arange(0.10, 0.901, 0.05), 2)


def accuracy_scores(actual, predicted):
    actual, predicted = np.asarray(actual), np.asarray(predicted)
    if actual.shape != predicted.shape or actual.size == 0:
        raise ValueError("Actual and predicted values must have the same nonempty shape")
    if not np.isfinite(actual).all() or not np.isfinite(predicted).all():
        raise ValueError("Cannot measure accuracy on nonfinite values")
    hits = np.abs(actual - predicted) <= TOLERANCE + 1e-12
    return {**scores(actual, predicted), "hit_rate_10pp": float(hits.mean()),
            "hits_10pp": int(hits.sum()), "rows": int(actual.size)}


class WindowRegressor:
    """Learn P(|power - center| <= .10 | available inputs) for each center.

    These are overlapping binary events, not mutually exclusive power classes.
    Select the center with the largest predicted event probability. The grid,
    tolerance and all model choices must be fixed before the regression period.
    """

    def __init__(self, depth=3, trees=250, early_stopping=False):
        options = dict(max_depth=depth, n_estimators=trees, learning_rate=0.045,
                       min_child_weight=30, reg_lambda=20, reg_alpha=0.1,
                       subsample=0.85, colsample_bytree=0.9, objective="binary:logistic",
                       eval_metric="logloss", tree_method="hist", n_jobs=4, random_state=42)
        if early_stopping:
            options["early_stopping_rounds"] = 25
        self.learner = XGBRegressor(**options)

    @staticmethod
    def labels(target):
        values = np.asarray(target, dtype=float)
        if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
            raise ValueError("Window targets must be finite normalized power in [0, 1]")
        return (np.abs(values[:, None] - CENTERS[None, :]) <= TOLERANCE + 1e-12).astype(float)

    def fit(self, features, target, eval_set=None, verbose=False):
        validation = None if eval_set is None else [(x, self.labels(y)) for x, y in eval_set]
        self.learner.fit(features, self.labels(target), eval_set=validation, verbose=False)
        return self

    def predict(self, features):
        probability = self.learner.predict(features)
        return CENTERS[np.argmax(probability, axis=1)]

    @property
    def best_iteration(self):
        return self.learner.best_iteration
