"""Tests for MQTT topic parsing and payload validation (FR-MQTT-01..02, FR-ING-02)."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.app.mqtt.payload import TelemetryPayload, parse_topic


@pytest.mark.parametrize(
    ("topic", "expected"),
    [
        ("weather/kit/kit01/telemetry", ("kit01", "telemetry")),
        ("weather/kit/KIT_02-a/status", ("KIT_02-a", "status")),
        ("weather/kit/kit01/other", None),
        ("weather/kit//telemetry", None),
        ("sites/x/kits/kit01/readings", None),
        ("weather/kit/kit01/telemetry/extra", None),
        ("weather/kit/" + "k" * 33 + "/telemetry", None),
    ],
)
def test_parse_topic(topic, expected):
    assert parse_topic(topic) == expected


def test_full_payload():
    payload = TelemetryPayload.model_validate_json(
        '{"ts": "2026-10-31T09:05:00Z", "temp_bme_c": 36.42, "hum_bme_pct": 41.8,'
        ' "pressure_hpa": 1004.21, "temp_dht_c": 37, "hum_dht_pct": 45, "wind_speed_ms": 6.7,'
        ' "wind_gust_ms": null, "rain_mm": null, "fw_version": "1.2.0", "extra": 1}'
    )
    assert payload.ts == datetime(2026, 10, 31, 9, 5, tzinfo=UTC)
    assert payload.temp_dht_c == 37.0
    assert payload.sensor_values()["wind_speed_ms"] == 6.7
    assert "extra" not in payload.sensor_values()


def test_missing_fields_become_none():
    payload = TelemetryPayload.model_validate_json('{"temp_dht_c": 35}')
    assert payload.ts is None
    assert payload.temp_bme_c is None


def test_naive_timestamp_is_utc():
    payload = TelemetryPayload.model_validate_json('{"ts": "2026-10-31T09:05:00"}')
    assert payload.ts.tzinfo == UTC


def test_offset_timestamp_is_converted_to_utc():
    payload = TelemetryPayload.model_validate_json('{"ts": "2026-10-31T14:35:00+05:30"}')
    assert payload.ts == datetime(2026, 10, 31, 9, 5, tzinfo=UTC)


@pytest.mark.parametrize(
    "raw",
    [
        '{"temp_bme_c": "36.4"}',
        '{"temp_bme_c": true}',
        '{"temp_bme_c": NaN}',
        '{"ts": "yesterday"}',
        "not json",
        "[1, 2]",
    ],
)
def test_invalid_payloads(raw):
    with pytest.raises(ValidationError):
        TelemetryPayload.model_validate_json(raw)
