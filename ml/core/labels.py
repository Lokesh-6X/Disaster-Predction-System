"""Training labels: will a hazard level be reached in the next 3 hours? (FR-ML-01, design §9.3)

Labels are cumulative ("this level or worse") and computed for every site-local
hour boundary *t* from the 5-min grid slots in (t, t + horizon].
"""

from __future__ import annotations

from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from ml.core.normals import DailyNormals

LABELS = (
    "wind_yellow",
    "wind_orange",
    "wind_red",
    "heat_yellow",
    "heat_orange",
    "heat_red",
)
MIN_WINDOW_COVERAGE = 0.75


def _forward_max(values: pd.Series, window: int, min_periods: int) -> np.ndarray:
    """Max over this slot and the next ``window - 1`` slots."""
    reversed_values = values.iloc[::-1].reset_index(drop=True)
    result = reversed_values.rolling(window, min_periods=min_periods).max().to_numpy()
    return result[::-1]


def make_labels(grid: pd.DataFrame, site, horizon_hours: int = 3) -> pd.DataFrame:
    """Labels indexed by prediction time *t* (site-local hour boundary, stored in UTC).

    ``grid`` is the 5-min grid from :func:`ml.core.aggregate.to_grid`. A label
    is NaN when less than 75 % of its window has data.
    """
    window = horizon_hours * 12
    min_periods = int(np.ceil(window * MIN_WINDOW_COVERAGE))
    # The window for t starts at the slot after t: slots t+5min .. t+horizon
    peak_wind_kmh = pd.Series(
        _forward_max(grid["wind_speed_ms"], window, min_periods) * 3.6, index=grid.index
    ).shift(-1)
    tmax = pd.Series(_forward_max(grid["temp_c"], window, min_periods), index=grid.index).shift(-1)

    local = grid.index.tz_convert(ZoneInfo(site.site.timezone))
    hourly = grid.index[local.minute == 0]  # site-local hour boundaries
    peak_wind_kmh = peak_wind_kmh.reindex(hourly)
    tmax = tmax.reindex(hourly)

    normals = DailyNormals(site.normals)
    local_doy = hourly.tz_convert(ZoneInfo(site.site.timezone)).dayofyear
    departure = tmax - normals.tmax_for(local_doy)

    wind = site.hazards.wind.levels
    heat = site.hazards.heat
    abs_threshold = site.heat_abs_threshold_c

    heat_red = tmax >= heat.red_abs_c
    hot = tmax >= abs_threshold
    raw = {
        "wind_yellow": peak_wind_kmh >= wind.yellow,
        "wind_orange": peak_wind_kmh >= wind.orange,
        "wind_red": peak_wind_kmh >= wind.red,
        "heat_yellow": (hot & (departure >= heat.departure_c.yellow)) | heat_red,
        "heat_orange": (hot & (departure >= heat.departure_c.orange)) | heat_red,
        "heat_red": heat_red,
    }
    labels = pd.DataFrame(raw, index=hourly).astype(float)
    labels.loc[peak_wind_kmh.isna(), ["wind_yellow", "wind_orange", "wind_red"]] = np.nan
    labels.loc[tmax.isna(), ["heat_yellow", "heat_orange", "heat_red"]] = np.nan
    labels["peak_wind_kmh"] = peak_wind_kmh
    labels["tmax_next"] = tmax
    labels.index.name = "t"
    return labels
