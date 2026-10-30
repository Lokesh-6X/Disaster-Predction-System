"""Tests for inference: hour boundaries, data sufficiency, predictions (FR-INF-01..03)."""

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from backend.app.inference.runner import (
    READING_COLUMNS,
    Sufficiency,
    assess_sufficiency,
    hour_boundary,
    predict,
)
from backend.app.settings import load_site_config
from ml.core.features import feature_names
from ml.core.labels import LABELS
from ml.registry import LoadedModels

SITE = load_site_config()
RUN_AT = datetime(2026, 5, 10, 8, 30, tzinfo=UTC)  # 14:00 IST


class StubModel:
    """Returns a fixed probability, looked up by label in a shared dict."""

    def __init__(self, probabilities: dict, label: str) -> None:
        self._probabilities = probabilities
        self._label = label

    def predict_proba(self, x):
        p = self._probabilities[self._label]
        return np.array([[1 - p, p]] * len(x))


def stub_models(probabilities: dict) -> LoadedModels:
    return LoadedModels(
        version="vtest",
        models={label: StubModel(probabilities, label) for label in LABELS},
        metadata={"feature_list": feature_names(), "data_source": "synthetic"},
    )


def readings(end: datetime, hours: float = 48, step_min: int = 5, **values) -> pd.DataFrame:
    count = int(hours * 60 / step_min)
    ts = pd.date_range(end=end - timedelta(minutes=step_min), periods=count, freq=f"{step_min}min")
    frame = pd.DataFrame(
        {
            "ts": ts,
            "temp_c": values.get("temp_c", 35.0),
            "hum_pct": 45.0,
            "pressure_hpa": 995.0,
            "wind_speed_ms": 3.0,
            "fallback": values.get("fallback", False),
        }
    )
    frame["qc_flags"] = [[] for _ in range(len(frame))]
    return frame[list(READING_COLUMNS)]


def test_hour_boundary_uses_site_clock():
    now = datetime(2026, 10, 31, 9, 17, tzinfo=UTC)  # 14:47 IST
    assert hour_boundary(now, "Asia/Kolkata") == datetime(2026, 10, 31, 8, 30, tzinfo=UTC)


def test_full_data_is_sufficient():
    result = assess_sufficiency(readings(RUN_AT), RUN_AT, SITE.data_sufficiency)
    assert result.ok
    assert result.missing_share_24h == 0
    assert result.minutes_since_last == 5


def test_no_recent_reading_is_insufficient():
    old = readings(RUN_AT - timedelta(minutes=70))
    result = assess_sufficiency(old, RUN_AT, SITE.data_sufficiency)
    assert not result.ok
    assert "no reading in the last 60 min" in result.reason


def test_too_much_missing_is_insufficient():
    data = readings(RUN_AT)
    day = data[data["ts"] >= RUN_AT - timedelta(hours=24)]
    gappy = data.drop(day.index[: int(len(day) * 0.3)])
    result = assess_sufficiency(gappy, RUN_AT, SITE.data_sufficiency)
    assert not result.ok
    assert "missing" in result.reason


def test_no_readings_is_insufficient():
    empty = readings(RUN_AT).iloc[0:0]
    assert not assess_sufficiency(empty, RUN_AT, SITE.data_sufficiency).ok


def test_one_minute_readings_count_once_per_slot():
    data = readings(RUN_AT, hours=24, step_min=1)
    assert assess_sufficiency(data, RUN_AT, SITE.data_sufficiency).missing_share_24h == 0


@pytest.mark.parametrize(
    ("p", "wind_level"),
    [
        ({"yellow": 0.2, "orange": 0.1, "red": 0.0}, "green"),
        ({"yellow": 0.8, "orange": 0.6, "red": 0.1}, "orange"),
        ({"yellow": 0.3, "orange": 0.7, "red": 0.9}, "green"),  # made monotonic: all 0.3
    ],
)
def test_predict_levels(p, wind_level):
    probabilities = {f"wind_{k}": v for k, v in p.items()}
    probabilities |= {f"heat_{k}": 0.0 for k in ("yellow", "orange", "red")}
    data = readings(RUN_AT)
    sufficiency = Sufficiency(True, 0.0, 5.0)
    wind, heat = predict("kit01", data, RUN_AT, SITE, stub_models(probabilities), sufficiency)

    assert (wind.hazard, heat.hazard) == ("wind", "heat")
    assert wind.level == wind_level
    assert heat.level == "green"
    assert wind.probabilities["orange"] <= wind.probabilities["yellow"]
    assert wind.valid_until == RUN_AT + timedelta(hours=3)
    assert wind.model_version == "vtest"
    assert wind.context["tmax_normal_c"] == pytest.approx(SITE.normals.tmax_c[4], abs=0.5)


def test_predict_reports_fallback_use():
    data = readings(RUN_AT)
    data.loc[data.index[-3], "fallback"] = True
    probabilities = dict.fromkeys(LABELS, 0.0)
    results = predict(
        "kit01", data, RUN_AT, SITE, stub_models(probabilities), Sufficiency(True, 0, 5)
    )
    assert all(p.fallback_used for p in results)


def test_predict_with_real_model_features():
    """The feature row given to the models has exactly the trained feature columns."""
    seen = {}

    class Recorder(StubModel):
        def predict_proba(self, x):
            seen["columns"] = list(x.columns)
            seen["rows"] = len(x)
            return super().predict_proba(x)

    probabilities = dict.fromkeys(LABELS, 0.1)
    models = stub_models(probabilities)
    models.models["wind_yellow"] = Recorder(probabilities, "wind_yellow")
    predict("kit01", readings(RUN_AT), RUN_AT, SITE, models, Sufficiency(True, 0, 5))
    assert seen == {"columns": feature_names(), "rows": 1}
