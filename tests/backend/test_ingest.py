"""Tests for the pure ingestion step: timestamp rules, QC and fusion (FR-ING-02..03)."""

import json
from datetime import UTC, datetime, timedelta

import pytest

from backend.app.ingest.pipeline import Rejected, prepare_reading
from backend.app.settings import load_site_config
from ml.core.qc import QcLimits

SITE = load_site_config()
LIMITS = QcLimits.from_config(SITE.qc)
NOW = datetime(2026, 10, 31, 9, 0, tzinfo=UTC)
GOOD = {
    "temp_bme_c": 32.0,
    "hum_bme_pct": 55.0,
    "pressure_hpa": 1000.0,
    "temp_dht_c": 33,
    "hum_dht_pct": 57,
    "wind_speed_ms": 3.0,
    "fw_version": "1.0",
}


def prepare(payload: dict, history=()):
    return prepare_reading("kit01", json.dumps(payload).encode(), NOW, list(history), SITE, LIMITS)


def iso(ts: datetime) -> str:
    return ts.isoformat().replace("+00:00", "Z")


def test_good_reading():
    reading = prepare({"ts": iso(NOW - timedelta(minutes=1)), **GOOD})
    assert reading.ts == NOW - timedelta(minutes=1)
    assert reading.ts_source == "kit"
    assert reading.received_at == NOW
    assert reading.temp_c == 32.0
    assert reading.qc_flags == []
    assert reading.values["rain_mm"] is None
    assert reading.fw_version == "1.0"


def test_missing_ts_uses_arrival_time():
    reading = prepare(GOOD)
    assert reading.ts == NOW
    assert reading.ts_source == "arrival"
    assert "ts_missing" in reading.qc_flags


def test_ts_slightly_ahead_is_accepted():
    assert prepare({"ts": iso(NOW + timedelta(minutes=9)), **GOOD}).ts_source == "kit"


def test_ts_far_in_future_is_rejected():
    with pytest.raises(Rejected, match="in the future"):
        prepare({"ts": iso(NOW + timedelta(minutes=11)), **GOOD})


def test_invalid_payload_is_rejected():
    with pytest.raises(Rejected, match="invalid payload"):
        prepare({**GOOD, "temp_bme_c": "hot"})


def test_bme_failure_falls_back_to_dht():
    reading = prepare({**GOOD, "temp_bme_c": None, "hum_bme_pct": None, "pressure_hpa": None})
    assert reading.fallback is True
    assert reading.temp_c == 33
    assert "temp_bme_c:null" in reading.qc_flags


def test_mismatch_flag_is_added():
    reading = prepare({**GOOD, "temp_dht_c": 40})
    assert "temp_c:bme_dht_mismatch" in reading.qc_flags


def test_row_has_all_columns():
    row = prepare(GOOD).to_row()
    assert set(row) == {
        "kit_id",
        "ts",
        "ts_source",
        "received_at",
        "temp_bme_c",
        "hum_bme_pct",
        "pressure_hpa",
        "temp_dht_c",
        "hum_dht_pct",
        "wind_speed_ms",
        "wind_gust_ms",
        "rain_mm",
        "temp_c",
        "hum_pct",
        "fallback",
        "qc_flags",
        "fw_version",
    }
