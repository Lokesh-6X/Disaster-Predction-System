"""From stored readings to a regular 5-minute grid and hourly aggregates (design §9.2).

Input: readings after QC and fusion (columns ``ts``, ``temp_c``, ``hum_pct``,
``pressure_hpa``, ``wind_speed_ms``, ``fallback``, ``qc_flags``). Values whose
QC flags make them unusable are removed first. Gaps up to ``max_gap_min``
minutes are filled by linear interpolation; longer gaps stay empty.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ml.core.qc import INVALIDATING_RULES, make_flag

GRID = pd.Timedelta(minutes=5)
SLOTS_PER_HOUR = 12
VARIABLES = ("temp_c", "hum_pct", "pressure_hpa", "wind_speed_ms")
# Variables measured by one sensor: invalid when that field is flagged
SINGLE_SENSOR = {"pressure_hpa": "pressure_hpa", "wind_speed_ms": "wind_speed_ms"}


def _valid_values(readings: pd.DataFrame) -> pd.DataFrame:
    frame = readings[["ts", *VARIABLES, "fallback"]].copy()
    flags = readings["qc_flags"]
    for column, field in SINGLE_SENSOR.items():
        bad = {make_flag(field, rule) for rule in INVALIDATING_RULES}
        invalid = flags.map(lambda fs, bad=bad: bool(bad.intersection(fs)))
        frame.loc[invalid.to_numpy(), column] = np.nan
    frame[list(VARIABLES)] = frame[list(VARIABLES)].astype(float)
    frame["fallback"] = frame["fallback"].astype(bool)
    return frame


def interpolate_short_gaps(series: pd.Series, max_gap_slots: int) -> pd.Series:
    """Linear interpolation only inside gaps of at most ``max_gap_slots`` missing slots."""
    missing = series.isna()
    if not missing.any():
        return series
    run_id = (missing != missing.shift()).cumsum()
    run_length = missing.groupby(run_id).transform("size")
    filled = series.interpolate(method="linear", limit_area="inside")
    fill_here = missing & (run_length <= max_gap_slots)
    return series.where(~fill_here, filled)


def to_grid(
    readings: pd.DataFrame,
    max_gap_min: int,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Regular 5-min grid (slot start index, UTC) of valid values, short gaps filled.

    Adds ``observed`` (slot had at least one reading with a temperature) and
    ``fallback`` (any reading in the slot used the DHT11).
    """
    frame = _valid_values(readings)
    frame["slot"] = frame["ts"].dt.floor(GRID)
    grouped = frame.groupby("slot")
    grid = grouped[list(VARIABLES)].mean()
    grid["fallback"] = grouped["fallback"].any()
    grid["observed"] = grouped["temp_c"].count() > 0

    start = start if start is not None else grid.index.min()
    end = end if end is not None else grid.index.max()
    full_index = pd.date_range(start.floor(GRID), end.floor(GRID), freq=GRID, name="slot")
    grid = grid.reindex(full_index)
    grid["fallback"] = grid["fallback"].fillna(False).astype(bool)
    grid["observed"] = grid["observed"].fillna(False).astype(bool)

    max_slots = max_gap_min // 5
    for column in VARIABLES:
        grid[column] = interpolate_short_gaps(grid[column], max_slots)
    return grid


def local_hour_start(index: pd.DatetimeIndex, timezone: str) -> pd.DatetimeIndex:
    """Start of the site-local clock hour containing each time, as UTC.

    Hours follow the site's clock (e.g. IST 14:00–15:00 = UTC 08:30–09:30) so
    predictions run "at 14:00" line up with what the admin sees.
    """
    return index.tz_convert(timezone).floor("h").tz_convert("UTC")


def to_hourly(grid: pd.DataFrame, timezone: str) -> pd.DataFrame:
    """Hourly aggregates indexed by local hour start (in UTC), on a complete hourly index."""
    hours = grid.groupby(local_hour_start(grid.index, timezone))
    hourly = pd.DataFrame(
        {
            "temp_mean": hours["temp_c"].mean(),
            "temp_max": hours["temp_c"].max(),
            "temp_min": hours["temp_c"].min(),
            "hum_mean": hours["hum_pct"].mean(),
            "pressure_mean": hours["pressure_hpa"].mean(),
            "pressure_last": hours["pressure_hpa"].last(),
            "wind_mean": hours["wind_speed_ms"].mean(),
            "wind_max": hours["wind_speed_ms"].max(),
            "n_observed": hours["observed"].sum(),
            "fallback_any": hours["fallback"].any(),
        }
    )
    full = pd.date_range(hourly.index.min(), hourly.index.max(), freq="h", name="hour")
    hourly = hourly.reindex(full)
    hourly["n_observed"] = hourly["n_observed"].fillna(0).astype(int)
    hourly["fallback_any"] = hourly["fallback_any"].fillna(False).astype(bool)
    return hourly
