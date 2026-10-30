"""Tests for BME280/DHT11 fusion (FR-QC-04)."""

from ml.core.fusion import fuse

LIMITS = {"temp_c": 3.0, "hum_pct": 10.0}
VALUES = {"temp_bme_c": 32.0, "hum_bme_pct": 55.0, "temp_dht_c": 33.0, "hum_dht_pct": 58.0}


def test_bme_is_primary():
    result = fuse(VALUES, [], LIMITS)
    assert (result.temp_c, result.hum_pct, result.fallback, result.flags) == (32.0, 55.0, False, ())


def test_dht_fallback_when_bme_missing():
    result = fuse({**VALUES, "temp_bme_c": None}, ["temp_bme_c:null"], LIMITS)
    assert result.temp_c == 33.0
    assert result.hum_pct == 55.0
    assert result.fallback is True


def test_dht_fallback_when_bme_flagged():
    result = fuse(VALUES, ["hum_bme_pct:stuck"], LIMITS)
    assert result.hum_pct == 58.0
    assert result.fallback is True


def test_flagged_dht_is_not_used():
    result = fuse(
        {**VALUES, "temp_bme_c": None},
        ["temp_bme_c:null", "temp_dht_c:spike"],
        LIMITS,
    )
    assert result.temp_c is None
    assert result.fallback is False


def test_large_disagreement_is_flagged():
    result = fuse({**VALUES, "temp_dht_c": 35.5, "hum_dht_pct": 70.0}, [], LIMITS)
    assert result.flags == ("temp_c:bme_dht_mismatch", "hum_pct:bme_dht_mismatch")
    assert result.temp_c == 32.0  # BME still used


def test_disagreement_at_limit_is_not_flagged():
    result = fuse({**VALUES, "temp_dht_c": 35.0, "hum_dht_pct": 65.0}, [], LIMITS)
    assert result.flags == ()
