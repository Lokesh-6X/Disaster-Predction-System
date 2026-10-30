"""Tests for normals, aggregation, labels, features and levels (FR-ML-01..02, FR-INF-03)."""

import numpy as np
import pandas as pd
import pytest

from backend.app.settings import load_site_config
from ml.core.aggregate import interpolate_short_gaps, to_grid, to_hourly
from ml.core.features import build_features, feature_names
from ml.core.labels import make_labels
from ml.core.levels import make_monotonic, select_level
from ml.core.normals import DailyNormals, daily_from_monthly

SITE = load_site_config()
NORMALS = DailyNormals(SITE.normals)
UTC = "UTC"
TZ = SITE.site.timezone


# ------------------------------------------------------------------ normals


def test_constant_monthly_values_give_constant_daily_values():
    assert np.allclose(daily_from_monthly([25.0] * 12), 25.0)


def test_mid_month_values_match_monthly_normals():
    mid_january, mid_may = 15, 135
    assert NORMALS.tmax_for(mid_january) == pytest.approx(SITE.normals.tmax_c[0], abs=0.3)
    assert NORMALS.tmax_for(mid_may) == pytest.approx(SITE.normals.tmax_c[4], abs=0.3)


def test_normals_wrap_smoothly_from_december_to_january():
    assert abs(NORMALS.tmax_for(365) - NORMALS.tmax_for(1)) < 0.2
    assert len(NORMALS.tmax_c) == 366


# -------------------------------------------------------------- aggregation


def test_interpolate_short_gaps_only():
    series = pd.Series([1.0] + [np.nan] * 6 + [8.0] + [np.nan] * 7 + [16.0])
    filled = interpolate_short_gaps(series, max_gap_slots=6)
    assert filled.iloc[1:7].tolist() == [2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
    assert filled.iloc[8:15].isna().all()


def readings_frame(times, **values) -> pd.DataFrame:
    n = len(times)
    frame = pd.DataFrame(
        {
            "ts": times,
            "temp_c": values.get("temp_c", np.full(n, 30.0)),
            "hum_pct": values.get("hum_pct", np.full(n, 50.0)),
            "pressure_hpa": values.get("pressure_hpa", np.full(n, 1000.0)),
            "wind_speed_ms": values.get("wind_speed_ms", np.full(n, 2.0)),
            "fallback": values.get("fallback", np.zeros(n, dtype=bool)),
        }
    )
    frame["qc_flags"] = values.get("qc_flags", [[] for _ in range(n)])
    return frame


def test_flagged_single_sensor_values_are_removed():
    times = pd.date_range("2026-05-01 00:00", periods=3, freq="5min", tz=UTC)
    flags = [[], ["pressure_hpa:spike"], []]
    grid = to_grid(readings_frame(times, pressure_hpa=[1000, 1010, 1000.0], qc_flags=flags), 0)
    assert np.isnan(grid["pressure_hpa"].iloc[1])


def test_hourly_aggregates():
    times = pd.date_range("2026-05-01 00:30", periods=24, freq="5min", tz=UTC)  # 06:00 IST
    temp = np.arange(24, dtype=float)
    hourly = to_hourly(to_grid(readings_frame(times, temp_c=temp), 30), TZ)
    first = hourly.iloc[0]
    assert (first["temp_min"], first["temp_max"], first["temp_mean"]) == (0, 11, 5.5)
    assert first["n_observed"] == 12


def test_one_minute_readings_are_averaged_into_slots():
    times = pd.date_range("2026-05-01 00:00", periods=10, freq="1min", tz=UTC)
    grid = to_grid(readings_frame(times, temp_c=np.arange(10, dtype=float)), 30)
    assert grid["temp_c"].tolist() == [2.0, 7.0]


# ------------------------------------------------------------------- labels


def label_grid(start: str, hours: int = 6, temp=30.0, wind_ms=1.0) -> pd.DataFrame:
    index = pd.date_range(start, periods=hours * 12, freq="5min", tz=UTC, name="slot")
    return pd.DataFrame(
        {"temp_c": np.full(len(index), temp), "wind_speed_ms": np.full(len(index), wind_ms)},
        index=index,
    )


def labels_with(grid: pd.DataFrame, minute: int, **values) -> pd.Series:
    """Set values at t + minute and return the labels for t = first slot."""
    t = grid.index[0]
    for column, value in values.items():
        grid.loc[t + pd.Timedelta(minutes=minute), column] = value
    return make_labels(grid, SITE).loc[t]


@pytest.mark.parametrize(
    ("kmh", "expected"),
    [(29.9, (0, 0, 0)), (30.1, (1, 0, 0)), (40.1, (1, 1, 0)), (59.9, (1, 1, 0)), (60.1, (1, 1, 1))],
)
def test_wind_label_boundaries(kmh, expected):
    labels = labels_with(label_grid("2026-07-01 06:30"), 60, wind_speed_ms=kmh / 3.6)
    assert (labels["wind_yellow"], labels["wind_orange"], labels["wind_red"]) == expected


def heat_labels(start: str, temp: float) -> tuple:
    labels = labels_with(label_grid(start), 60, temp_c=temp)
    return labels["heat_yellow"], labels["heat_orange"], labels["heat_red"]


def test_heat_label_boundaries_in_may():
    start = "2026-05-15 06:30"  # 12:00 IST
    normal = float(
        NORMALS.tmax_for(pd.Timestamp(start).tz_localize(UTC).tz_convert("Asia/Kolkata").dayofyear)
    )
    assert normal + 4.4 >= 40  # so departure decides
    assert heat_labels(start, normal + 4.4) == (0, 0, 0)
    assert heat_labels(start, normal + 4.6) == (1, 0, 0)
    assert heat_labels(start, normal + 6.6) == (1, 1, 0)
    assert heat_labels(start, 45.0) == (1, 1, 1)


def test_heat_needs_forty_degrees_even_with_large_departure():
    # January normal max ≈ 30.7 °C: 37 °C is +6 °C but below the 40 °C floor
    assert heat_labels("2026-01-15 06:30", 37.0) == (0, 0, 0)


def test_label_window_excludes_t_and_includes_t_plus_three_hours():
    assert labels_with(label_grid("2026-07-01 06:30"), 0, wind_speed_ms=20)["wind_yellow"] == 0
    assert labels_with(label_grid("2026-07-01 06:30"), 180, wind_speed_ms=20)["wind_yellow"] == 1
    assert labels_with(label_grid("2026-07-01 06:30"), 185, wind_speed_ms=20)["wind_yellow"] == 0


def test_label_is_missing_when_window_has_little_data():
    grid = label_grid("2026-07-01 06:30")
    grid.iloc[1:20, :] = np.nan  # 19 of 36 window slots missing
    assert np.isnan(make_labels(grid, SITE).iloc[0]["wind_yellow"])


# ----------------------------------------------------------------- features


def hourly_frame(hours: int = 72) -> pd.DataFrame:
    times = pd.date_range("2026-05-01 00:00", periods=hours * 12, freq="5min", tz=UTC)
    temp = 30 + 5 * np.sin(np.arange(len(times)) / 50)
    return to_hourly(to_grid(readings_frame(times, temp_c=temp), 30), TZ)


def test_feature_columns_match_feature_names():
    features = build_features(hourly_frame(), SITE)
    assert list(features.columns) == feature_names()
    assert len(feature_names()) == 95


def test_features_do_not_look_ahead():
    hourly = hourly_frame()
    t = hourly.index[40] + pd.Timedelta(hours=1)  # prediction time after hour 40
    before = build_features(hourly, SITE).loc[t]
    changed = hourly.copy()
    changed.iloc[41:, :] = changed.iloc[41:, :].apply(lambda c: c * 2 if c.dtype.kind == "f" else c)
    after = build_features(changed, SITE).loc[t]
    pd.testing.assert_series_equal(before, after)


def test_feature_lags_refer_to_earlier_hours():
    hourly = hourly_frame()
    features = build_features(hourly, SITE)
    t = hourly.index[30] + pd.Timedelta(hours=1)
    assert features.loc[t, "temp_mean"] == hourly["temp_mean"].iloc[30]
    assert features.loc[t, "temp_mean_lag1"] == hourly["temp_mean"].iloc[29]
    assert features.loc[t, "temp_mean_lag24"] == hourly["temp_mean"].iloc[6]


# ------------------------------------------------------------------- levels


def test_probabilities_are_made_monotonic():
    assert make_monotonic({"yellow": 0.4, "orange": 0.6, "red": 0.7}) == {
        "yellow": 0.4,
        "orange": 0.4,
        "red": 0.4,
    }


@pytest.mark.parametrize(
    ("probabilities", "level"),
    [
        ({"yellow": 0.49, "orange": 0.1, "red": 0.0}, "green"),
        ({"yellow": 0.5, "orange": 0.2, "red": 0.0}, "yellow"),
        ({"yellow": 0.9, "orange": 0.55, "red": 0.3}, "orange"),
        ({"yellow": 0.9, "orange": 0.8, "red": 0.5}, "red"),
    ],
)
def test_select_level(probabilities, level):
    assert select_level(probabilities, 0.5) == level
