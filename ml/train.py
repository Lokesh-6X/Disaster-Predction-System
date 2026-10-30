"""Train the six XGBoost classifiers (FR-ML-03, design §9.5).

v1 decisions: library-default hyper-parameters, random stratified 80/20 split,
no class weighting.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from sklearn.model_selection import train_test_split
from xgboost import XGBClassifier

from ml.core.features import feature_names
from ml.core.labels import LABELS
from ml.evaluate import evaluate_model

TEST_SIZE = 0.2
MIN_POSITIVES = 10


class TrainingError(Exception):
    pass


@dataclass
class TrainResult:
    models: dict[str, XGBClassifier]
    metrics: dict[str, dict]
    rows: dict[str, int]


def train_models(data: pd.DataFrame, seed: int) -> TrainResult:
    features = feature_names()
    models: dict[str, XGBClassifier] = {}
    metrics: dict[str, dict] = {}
    rows: dict[str, int] = {}
    for label in LABELS:
        subset = data[data[label].notna()]
        x, y = subset[features], subset[label].astype(int)
        positives = int(y.sum())
        if positives < MIN_POSITIVES:
            raise TrainingError(
                f"{label}: only {positives} positive hours — need at least {MIN_POSITIVES}. "
                "Increase event rates or years in synthetic.yaml."
            )
        x_train, x_test, y_train, y_test = train_test_split(
            x, y, test_size=TEST_SIZE, random_state=seed, stratify=y
        )
        model = XGBClassifier(random_state=seed, n_jobs=-1, eval_metric="logloss")
        model.fit(x_train, y_train)
        models[label] = model
        metrics[label] = evaluate_model(model, x_test, y_test)
        rows[label] = len(subset)
    return TrainResult(models=models, metrics=metrics, rows=rows)
