"""Model evaluation metrics (FR-ML-04, design §9.6)."""

from __future__ import annotations

import pandas as pd
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
from xgboost import XGBClassifier

THRESHOLD = 0.5
TOP_FEATURES = 15
NOTE = "Synthetic data, random 80/20 split — these scores do not reflect real-world accuracy."


def evaluate_model(model: XGBClassifier, x_test: pd.DataFrame, y_test: pd.Series) -> dict:
    probability = model.predict_proba(x_test)[:, 1]
    predicted = (probability >= THRESHOLD).astype(int)
    gain = model.get_booster().get_score(importance_type="gain")
    top = sorted(gain.items(), key=lambda item: item[1], reverse=True)[:TOP_FEATURES]
    return {
        "n_test": int(len(y_test)),
        "positives_test": int(y_test.sum()),
        "positive_rate": float(y_test.mean()),
        "precision": float(precision_score(y_test, predicted, zero_division=0)),
        "recall": float(recall_score(y_test, predicted, zero_division=0)),
        "f1": float(f1_score(y_test, predicted, zero_division=0)),
        "pr_auc": float(average_precision_score(y_test, probability)),
        "brier": float(brier_score_loss(y_test, probability)),
        "top_features": [{"feature": name, "gain": round(float(value), 3)} for name, value in top],
    }


def summary_table(metrics: dict[str, dict]) -> str:
    header = (
        f"{'model':<13}{'test':>7}{'pos':>6}{'precision':>11}"
        f"{'recall':>8}{'F1':>7}{'PR-AUC':>8}{'Brier':>8}"
    )
    lines = [header, "-" * len(header)]
    for label, m in metrics.items():
        lines.append(
            f"{label:<13}{m['n_test']:>7}{m['positives_test']:>6}{m['precision']:>11.3f}"
            f"{m['recall']:>8.3f}{m['f1']:>7.3f}{m['pr_auc']:>8.3f}{m['brier']:>8.4f}"
        )
    lines.append(NOTE)
    return "\n".join(lines)


def top_features_text(metrics: dict[str, dict], count: int = 5) -> str:
    lines = []
    for label, m in metrics.items():
        names = ", ".join(f["feature"] for f in m["top_features"][:count])
        lines.append(f"{label:<13}{names}")
    return "\n".join(lines)
