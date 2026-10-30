"""Tests for the synthetic generator, batch QC and the model registry (FR-SYN, FR-ML-05)."""

import numpy as np
import pandas as pd
import pytest
from xgboost import XGBClassifier

from backend.app.settings import load_site_config, load_synthetic_config
from ml import registry
from ml.core.batch import qc_and_fuse
from ml.core.features import feature_names
from ml.core.labels import LABELS
from ml.core.qc import QcLimits
from ml.synthetic.generator import generate

SITE = load_site_config()
SYN = load_synthetic_config(site=SITE)
PAYLOAD_COLUMNS = [
    "ts",
    "kit_id",
    "temp_bme_c",
    "hum_bme_pct",
    "pressure_hpa",
    "temp_dht_c",
    "hum_dht_pct",
    "wind_speed_ms",
    "wind_gust_ms",
    "rain_mm",
    "fw_version",
]


@pytest.fixture(scope="module")
def result():
    return generate(SITE, SYN)


def test_readings_use_the_kit_payload_format(result):
    readings = result.readings
    assert list(readings.columns) == PAYLOAD_COLUMNS
    assert str(readings["ts"].dt.tz) == "UTC"
    assert readings["ts"].is_monotonic_increasing
    assert readings["temp_dht_c"].dropna().mod(1).eq(0).all()  # DHT11: whole numbers
    assert readings["rain_mm"].isna().all()


def test_hazard_share_is_within_target(result):
    low, high = SYN.target_hazard_hour_share
    assert low <= result.shares["hazard_any"] <= high


def test_every_label_has_enough_positive_hours(result):
    assert min(result.shares["positive_hours"].values()) >= 20


def test_climate_matches_normals(result):
    local = result.truth.index.tz_convert("Asia/Kolkata")
    daily_max = result.truth["temp_c"].groupby(local.date).max()
    months = pd.to_datetime(daily_max.index).month
    mean_daily_max = daily_max.groupby(months).mean()
    for month in (1, 7, 12):  # months without heat spells
        assert mean_daily_max[month] == pytest.approx(SITE.normals.tmax_c[month - 1], abs=1.5)


def test_generator_is_reproducible():
    small = SYN.model_copy(update={"years": 1})
    first, second = generate(SITE, small), generate(SITE, small)
    pd.testing.assert_frame_equal(first.readings, second.readings)


def test_faults_are_injected_and_qc_finds_spikes(result):
    assert {"spike", "stuck", "gap", "offline", "bme_failure"} <= set(result.faults["type"])
    month = result.readings[
        result.readings["ts"] < result.readings["ts"].min() + pd.Timedelta(days=30)
    ]
    checked = qc_and_fuse(
        month, QcLimits.from_config(SITE.qc), SITE.qc.fusion_mismatch.model_dump()
    )
    flags = dict(zip(checked["ts"], checked["qc_flags"], strict=True))
    spikes = result.faults[
        (result.faults["type"] == "spike") & (result.faults["start"] < month["ts"].max())
    ]
    caught = sum(
        any(f.startswith(row.field + ":") for f in flags.get(row.start, []))
        for row in spikes.itertuples()
    )
    assert len(spikes) > 20
    assert caught / len(spikes) > 0.9


# ----------------------------------------------------------------- registry


def tiny_models() -> dict[str, XGBClassifier]:
    rng = np.random.default_rng(0)
    x = pd.DataFrame(rng.normal(size=(60, len(feature_names()))), columns=feature_names())
    y = (x.iloc[:, 0] > 0).astype(int)
    return {label: XGBClassifier(n_estimators=3).fit(x, y) for label in LABELS}


def test_registry_round_trip(tmp_path):
    models = tiny_models()
    version = registry.save_version(models, {"feature_list": feature_names()}, tmp_path)
    assert version == "v1"
    assert registry.next_version(tmp_path) == "v2"
    registry.activate(version, tmp_path)
    loaded = registry.load_active(tmp_path)
    x = pd.DataFrame(np.zeros((1, len(feature_names()))), columns=feature_names())
    for label in LABELS:
        assert loaded.models[label].predict_proba(x)[0, 1] == pytest.approx(
            models[label].predict_proba(x)[0, 1]
        )


def test_registry_rejects_unknown_version_and_feature_mismatch(tmp_path):
    with pytest.raises(registry.RegistryError):
        registry.activate("v9", tmp_path)
    version = registry.save_version(tiny_models(), {"feature_list": ["other"]}, tmp_path)
    with pytest.raises(registry.RegistryError, match="different feature list"):
        registry.load_version(version, tmp_path)
