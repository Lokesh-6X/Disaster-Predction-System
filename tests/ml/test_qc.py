"""Tests for QC rules (FR-QC-01..03)."""

from datetime import UTC, datetime, timedelta

import pytest

from backend.app.settings import load_site_config
from ml.core.qc import QcLimits, QcReading, check_reading

LIMITS = QcLimits.from_config(load_site_config().qc)
T0 = datetime(2026, 5, 1, 9, 0, tzinfo=UTC)

GOOD = {
    "temp_bme_c": 32.0,
    "hum_bme_pct": 55.0,
    "pressure_hpa": 1000.0,
    "temp_dht_c": 33.0,
    "hum_dht_pct": 57.0,
    "wind_speed_ms": 3.0,
}


def values(**changes):
    return {**GOOD, **changes}


def series(minutes: int, step_min: int = 5, **changes) -> list[QcReading]:
    """Readings every step_min minutes covering `minutes` before T0 (oldest first)."""
    count = minutes // step_min
    return [
        QcReading(ts=T0 - timedelta(minutes=step_min * i), values=values(**changes))
        for i in range(count, 0, -1)
    ]


def test_good_reading_has_no_flags():
    assert check_reading(T0, GOOD, [], LIMITS) == []


def test_null_values_are_flagged():
    flags = check_reading(T0, values(temp_bme_c=None, wind_speed_ms=None), [], LIMITS)
    assert flags == ["temp_bme_c:null", "wind_speed_ms:null"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("temp_bme_c", 56),
        ("temp_dht_c", -1),
        ("hum_bme_pct", 101),
        ("pressure_hpa", 900),
        ("wind_speed_ms", 61),
    ],
)
def test_out_of_range(field, value):
    assert check_reading(T0, values(**{field: value}), [], LIMITS) == [f"{field}:out_of_range"]


def test_range_limits_are_inclusive():
    assert check_reading(T0, values(temp_bme_c=55, hum_bme_pct=0), [], LIMITS) == []


def test_spike_uses_change_per_minute():
    history = [QcReading(T0 - timedelta(minutes=5), values())]
    # 5 °C in 5 min = 1 °C/min: allowed; 5.5 °C in 5 min: spike
    assert check_reading(T0, values(temp_bme_c=37.0), history, LIMITS) == []
    flags = check_reading(T0, values(temp_bme_c=37.5), history, LIMITS)
    assert flags == ["temp_bme_c:spike"]


def test_pressure_spike():
    history = [QcReading(T0 - timedelta(minutes=5), values())]
    assert check_reading(T0, values(pressure_hpa=1004.0), history, LIMITS) == ["pressure_hpa:spike"]


def test_no_spike_check_after_long_gap():
    history = [QcReading(T0 - timedelta(minutes=20), values())]
    assert check_reading(T0, values(temp_bme_c=45.0), history, LIMITS) == []


def test_spike_compares_with_last_valid_value():
    history = [
        QcReading(T0 - timedelta(minutes=10), values()),
        QcReading(
            T0 - timedelta(minutes=5), values(temp_bme_c=50.0), frozenset({"temp_bme_c:spike"})
        ),
    ]
    # Back to normal: compared with 32 °C ten minutes ago, not with the spike
    assert check_reading(T0, values(temp_bme_c=32.5), history, LIMITS) == []


def test_wind_has_no_spike_check():
    history = [QcReading(T0 - timedelta(minutes=5), values(wind_speed_ms=1.0))]
    assert check_reading(T0, values(wind_speed_ms=20.0), history, LIMITS) == []


def test_stuck_after_sixty_minutes():
    assert (
        check_reading(T0, GOOD, series(60, pressure_hpa=1000.0), LIMITS).count("pressure_hpa:stuck")
        == 1
    )


def test_not_stuck_before_sixty_minutes():
    flags = check_reading(T0, GOOD, series(55), LIMITS)
    assert not any(f.endswith(":stuck") for f in flags)


def test_dht_gets_a_longer_stuck_window():
    flags = check_reading(T0, GOOD, series(120), LIMITS)
    assert "temp_bme_c:stuck" in flags
    assert "temp_dht_c:stuck" not in flags
    flags = check_reading(T0, GOOD, series(180), LIMITS)
    assert "temp_dht_c:stuck" in flags


def test_calm_wind_is_never_stuck():
    flags = check_reading(T0, values(wind_speed_ms=0), series(120, wind_speed_ms=0), LIMITS)
    assert "wind_speed_ms:stuck" not in flags


def test_stuck_needs_enough_readings():
    history = [QcReading(T0 - timedelta(minutes=90), values())]
    flags = check_reading(T0, GOOD, history, LIMITS)
    assert not any(f.endswith(":stuck") for f in flags)


def test_later_history_is_ignored():
    history = [QcReading(T0 + timedelta(minutes=5), values(temp_bme_c=10.0))]
    assert check_reading(T0, GOOD, history, LIMITS) == []
